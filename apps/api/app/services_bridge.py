"""Pont base de données <-> moteur d'optimisation (planning_solver)."""
import uuid
from collections import defaultdict
from datetime import date, time, timedelta
from typing import Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from planning_solver.model import (Assignment as SAssign, BrandBudget, Contract, DEFAULT_WEIGHTS,
                                   Employee as SEmployee, Slot, SolverConfig, SolverInput)
from planning_solver.timecalc import shift_hours, split_allocation

from . import models as m


def _t(s: str) -> time:
    return time.fromisoformat(s)


def _active(c: m.ConstraintDefinition, start: date, end: date) -> bool:
    return c.enabled and (c.valid_from is None or c.valid_from <= end) and (c.valid_to is None or c.valid_to >= start)


def build_input(db: Session, period: m.PlanningPeriod, cfg_overrides: Optional[dict] = None) -> SolverInput:
    cfg_overrides = cfg_overrides or {}
    start, end = period.start_date, period.end_date
    brands = {b.code: b for b in db.scalars(select(m.Brand))}
    templates = {t.id: t for t in db.scalars(select(m.ShiftTemplate))}
    slots: List[Slot] = []
    d = start
    reqs = list(db.scalars(select(m.StaffingRequirement)))
    while d <= end:
        for r in reqs:
            days_ok = (d.isoformat() in (r.dates or [])) if r.dates else (d.weekday() in (r.weekdays or []))
            if not days_ok:
                continue
            # jours de fonctionnement des marques : contrainte dure
            if any(brands.get(b) and brands[b].active_weekdays and d.weekday() not in brands[b].active_weekdays
                   for b in r.allocations):
                continue
            t = templates[r.template_id]
            h = shift_hours(d, t.start_time, t.end_time, t.break_minutes)
            slots.append(Slot(
                f"{r.code}|{d.isoformat()}", d, r.site_code, t.start_time, t.end_time, t.break_minutes,
                split_allocation(h.effective_minutes, {k: float(v) for k, v in r.allocations.items()}),
                tag=t.tag, template_id=t.code, required_skills=tuple(r.required_skills or ()),
                mandatory=r.mandatory, day_group=f"{r.flex_group}|{d.isoformat()}" if r.flex_group else None,
                stagger_group=r.stagger_group))
        d += timedelta(days=1)

    skills = {s.id: s.code for s in db.scalars(select(m.Skill))}
    emp_skills: Dict[uuid.UUID, set] = defaultdict(set)
    for es in db.scalars(select(m.EmployeeSkill)):
        emp_skills[es.employee_id].add(skills.get(es.skill_id))
    contracts: Dict[uuid.UUID, m.EmploymentContract] = {}
    for c in db.scalars(select(m.EmploymentContract)):
        if (c.start_date is None or c.start_date <= end) and (c.end_date is None or c.end_date >= start):
            contracts[c.employee_id] = c
    avail: Dict[uuid.UUID, set] = defaultdict(set)
    for a in db.scalars(select(m.Availability)):
        avail[a.employee_id].add(a.weekday)
    unav_wd: Dict[uuid.UUID, set] = defaultdict(set)
    unav_dt: Dict[uuid.UUID, set] = defaultdict(set)
    for u in db.scalars(select(m.Unavailability)):
        (unav_wd if u.weekday is not None else unav_dt)[u.employee_id].add(u.weekday if u.weekday is not None
                                                                          else u.on_date)
    leaves = list(db.scalars(select(m.LeaveRequest).where(m.LeaveRequest.status == "approved")))
    for lv in leaves:
        x = lv.start_date
        while x <= lv.end_date:
            unav_dt[lv.employee_id].add(x)
            x += timedelta(days=1)
    rules = [c for c in db.scalars(select(m.ConstraintDefinition)) if _active(c, start, end)]
    prefs: Dict[uuid.UUID, list] = defaultdict(list)
    for p in db.scalars(select(m.EmployeePreference)):
        prefs[p.employee_id].append(p)
    rel = {r.employee_id: r.other_employee_id for r in db.scalars(select(m.RelationshipPreference))}
    codes = {e.id: e.code for e in db.scalars(select(m.Employee))}

    emps: List[SEmployee] = []
    for e in db.scalars(select(m.Employee).where(m.Employee.active.is_(True)).order_by(m.Employee.code)):
        se = SEmployee(e.code, e.name, dict(e.brands or {}), skills={s for s in emp_skills[e.id] if s},
                       weight=e.allocation_weight,
                       available_weekdays=set(avail[e.id]) if avail.get(e.id) else None,
                       unavailable_weekdays=set(unav_wd[e.id]), unavailable_dates=set(unav_dt[e.id]),
                       opposite_of=codes.get(rel.get(e.id)) if e.id in rel else None)
        c = contracts.get(e.id)
        if c:
            se.contract = Contract(c.activity_rate, c.monthly_min_minutes, c.monthly_target_minutes,
                                   c.monthly_max_minutes, c.weekly_max_minutes, c.overtime_allowed)
        for r in rules:
            if r.scope == "employee" and r.employee_id == e.id:
                if r.code == "forbidden_tag":
                    se.forbidden_tags |= set(r.params.get("tags", []))
                elif r.code == "max_days_per_week":
                    se.max_days_per_week = int(r.params["value"])
        for p in prefs[e.id]:
            P = p.params
            if p.kind == "latest_start":
                se.latest_start = _t(P["time"])
            elif p.kind == "preferred_times":
                se.preferred_times |= {(_t(a), _t(b)) for a, b in P["times"]}
                se.preference_strength = max(se.preference_strength, p.strength)
            elif p.kind == "preferred_tags":
                se.preferred_tags |= set(P["tags"])
                se.preference_strength = max(se.preference_strength, p.strength)
            elif p.kind == "weekly_rest_days":
                se.weekly_rest_days_pref = int(P["days"])
                se.weekly_rest_days_hard = p.is_hard
        emps.append(se)

    cfg = SolverConfig(weights=dict(DEFAULT_WEIGHTS))
    for r in sorted(rules, key=lambda r: r.version):
        if r.scope != "tenant":
            continue
        if r.code == "rest_hours":
            cfg.rest_hours = int(r.params["value"])
        elif r.code == "max_consecutive_days":
            cfg.max_consecutive_days = int(r.params["value"])
        elif r.code == "weights":
            cfg.weights.update({k: int(v) for k, v in r.params.items() if k in DEFAULT_WEIGHTS})
    for k, v in cfg_overrides.items():
        if k == "weights":
            cfg.weights.update({a: int(b) for a, b in v.items() if a in DEFAULT_WEIGHTS})
        elif k in ("time_limit_s", "workers", "strict_coverage", "seed"):
            setattr(cfg, k, v)

    budgets = [BrandBudget(b.brand_code, b.target_minutes, b.requirements_defined)
               for b in db.scalars(select(m.MonthlyBudget).where(
                   m.MonthlyBudget.month == start.replace(day=1)))]
    used = {r.template_id for r in reqs}
    hyp = [f"Horaire supposé NON VALIDÉ : modèle {t.code} {t.start_time:%H:%M}-{t.end_time:%H:%M}"
           f"{' — ' + t.hypothesis_note if t.hypothesis_note else ''}. À confirmer ou modifier (paramétrable)."
           for t in templates.values() if t.is_hypothesis and t.id in used]
    inp = SolverInput(start, end, slots, emps, budgets, cfg, leaves_provided=bool(leaves), hypotheses=sorted(hyp))
    return inp


def current_assignments(db: Session, period: m.PlanningPeriod) -> Tuple[Dict[str, str], Dict[str, str]]:
    """(previous, locked) : slot_key -> employee code."""
    codes = {e.id: e.code for e in db.scalars(select(m.Employee))}
    shifts = {s.id: s for s in db.scalars(select(m.Shift).where(m.Shift.period_id == period.id))}
    prev, locked = {}, {}
    for a in db.scalars(select(m.Assignment).where(m.Assignment.period_id == period.id)):
        key = shifts[a.shift_id].slot_key
        prev[key] = codes[a.employee_id]
        if a.locked:
            locked[key] = codes[a.employee_id]
    return prev, locked


def assignments_for_validation(db: Session, inp: SolverInput, period: m.PlanningPeriod) -> List[SAssign]:
    codes = {e.id: e.code for e in db.scalars(select(m.Employee))}
    slots = {s.id: s for s in inp.slots}
    shifts = {s.id: s for s in db.scalars(select(m.Shift).where(m.Shift.period_id == period.id))}
    out = []
    import dataclasses
    for i, s0 in enumerate(inp.slots):  # horaires modifiés manuellement : la base fait foi
        sh0 = next((x for x in shifts.values() if x.slot_key == s0.id), None)
        if sh0 and (sh0.start_time, sh0.end_time, sh0.break_minutes) != (s0.start, s0.end, s0.break_minutes):
            inp.slots[i] = dataclasses.replace(s0, start=sh0.start_time, end=sh0.end_time,
                                               break_minutes=sh0.break_minutes)
    slots = {s.id: s for s in inp.slots}
    for a in db.scalars(select(m.Assignment).where(m.Assignment.period_id == period.id)):
        sh = shifts[a.shift_id]
        s = slots.get(sh.slot_key)
        if s is None:
            continue
        h = s.hours
        out.append(SAssign(s.id, codes[a.employee_id], s.day, s.start, s.end, h.presence_minutes, h.break_minutes,
                           h.effective_minutes, dict(s.allocations), a.locked))
    return out


def persist_result(db: Session, tenant_id, period: m.PlanningPeriod, inp: SolverInput, res, run_id) -> None:
    """Remplace les affectations non verrouillées par le résultat ; les verrouillées sont conservées."""
    codes = {e.code: e.id for e in db.scalars(select(m.Employee))}
    shifts = {s.slot_key: s for s in db.scalars(select(m.Shift).where(m.Shift.period_id == period.id))}
    existing = list(db.scalars(select(m.Assignment).where(m.Assignment.period_id == period.id)))
    keep = {a.shift_id for a in existing if a.locked}
    for a in existing:
        if not a.locked:
            db.delete(a)
    db.flush()
    slots = {s.id: s for s in inp.slots}
    assigned = {a.slot_id for a in res.assignments}
    for s in inp.slots:
        if (s.mandatory or s.id in assigned) and s.id not in shifts:
            h = s.hours
            sh = m.Shift(tenant_id=tenant_id, period_id=period.id, slot_key=s.id, day=s.day, site_code=s.site,
                         start_time=s.start, end_time=s.end, break_minutes=s.break_minutes,
                         presence_minutes=h.presence_minutes, effective_minutes=h.effective_minutes)
            db.add(sh)
            shifts[s.id] = sh
    db.flush()
    for a in res.assignments:
        sh = shifts[a.slot_id]
        if sh.id in keep:
            continue
        row = m.Assignment(tenant_id=tenant_id, period_id=period.id, shift_id=sh.id, employee_id=codes[a.employee_id],
                           run_id=run_id, source="solver", locked=False)
        db.add(row)
        db.flush()
        if sh.break_minutes:
            db.add(m.Break(tenant_id=tenant_id, assignment_id=row.id, minutes=sh.break_minutes, paid=False))
        for b, mins in a.allocations.items():
            db.add(m.BrandAllocation(tenant_id=tenant_id, assignment_id=row.id, brand_code=b, minutes=mins))
    # shifts devenus sans affectation et non obligatoires : supprimés
    db.flush()
    used = {a.shift_id for a in db.scalars(select(m.Assignment).where(m.Assignment.period_id == period.id))}
    for key, sh in list(shifts.items()):
        s = slots.get(key)
        if sh.id not in used and (s is None or not s.mandatory):
            db.delete(sh)
