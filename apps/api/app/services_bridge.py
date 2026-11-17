"""Pont base de données <-> moteur d'optimisation (planning_solver)."""
import uuid
from collections import defaultdict
from datetime import date, time, timedelta
from typing import Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from planning_solver.model import (Assignment as SAssign, BrandBudget, Contract, DEFAULT_WEIGHTS,
                                   Employee as SEmployee, OutsideShift, Relation, Slot, SolverConfig, SolverInput)
from planning_solver.strategies import BY_KEY as STRATEGIES, apply_strategy
from planning_solver.timecalc import shift_hours, split_allocation
from planning_solver.weights import engine_weights

from . import models as m
from .frozen import apply_config, apply_fiche, config_of, fiche_of


def _t(s: str) -> time:
    return time.fromisoformat(s)


def _active(c: m.ConstraintDefinition, start: date, end: date) -> bool:
    return c.enabled and (c.valid_from is None or c.valid_from <= end) and (c.valid_to is None or c.valid_to >= start)


PLANNED_MISSION_STATUSES = ("confirmed", "completed")


def _regime_value(rules: Dict[Optional[str], int], regime: Optional[str]) -> Optional[int]:
    """Valeur du régime du contrat ; à défaut, règle générale du tenant ; à défaut, aucune."""
    return rules.get(regime, rules.get(None)) if regime else rules.get(None)


def params_mode(period: m.PlanningPeriod, cfg_overrides: Optional[dict] = None) -> str:
    """« frozen » : paramètres conservés par le planning ; « current » : paramètres actuels (planning sans paramètres conservés, ou choix explicite)."""
    want = (cfg_overrides or {}).get("params")
    if want == "current" or not getattr(period, "frozen_params", None):
        return "current"
    return "frozen"


def tenant_cap(db: Session, tenant_id) -> Optional[int]:
    t = db.get(m.Tenant, tenant_id) if tenant_id else None
    return t.monthly_hours_cap_minutes if t is not None else None


def build_input(db: Session, period: m.PlanningPeriod, cfg_overrides: Optional[dict] = None, toggles: bool = True,
                capture: Optional[dict] = None) -> SolverInput:
    """`toggles=False` : ignore les marques/sites désactivés pour le mois (sert à afficher les besoins « si activé »).
    `cfg_overrides["params"]` : « current » = paramètres actuels même si le planning en conserve ; sinon ceux du planning s'il en a.
    `cfg_overrides["cap"]` : « current » = plafond mensuel actuel de l'entreprise (toute génération et toute modification manuelle).
    `capture` : reçoit les paramètres habituels ACTUELS {"employees": {code: fiche}, "config": {...}, "names": {code: nom}}."""
    cfg_overrides = cfg_overrides or {}
    frozen = period.frozen_params if params_mode(period, cfg_overrides) == "frozen" else None
    start, end = period.start_date, period.end_date
    brands = {b.code: b for b in db.scalars(select(m.Brand))}
    templates = {t.id: t for t in db.scalars(select(m.ShiftTemplate))}
    slots: List[Slot] = []
    d = start
    pid = getattr(period, "id", None) if toggles else None
    off_brands = {x.brand_code for x in db.scalars(select(m.PeriodBrand).where(m.PeriodBrand.period_id == pid, m.PeriodBrand.active.is_(False)))} if pid else set()
    off_sites = {x.site_code for x in db.scalars(select(m.PeriodSite).where(m.PeriodSite.period_id == pid, m.PeriodSite.active.is_(False)))} if pid else set()
    off_brands |= {b.code for b in brands.values() if b.archived_from and b.archived_from <= start}  # archivé à partir d'un mois : les mois antérieurs restent intacts
    off_sites |= {x.code for x in db.scalars(select(m.Site)) if x.archived_from and x.archived_from <= start}
    missions = {x.id: x for x in db.scalars(select(m.Mission))}
    reqs = [r for r in db.scalars(select(m.StaffingRequirement))
            if (r.valid_from is None or r.valid_from <= end) and (r.valid_to is None or r.valid_to >= start)  # version de besoin en vigueur
            and r.site_code not in off_sites and not any(b in off_brands for b in r.allocations)
            and (r.mission_id is None or (r.mission_id in missions and missions[r.mission_id].status in PLANNED_MISSION_STATUSES))]  # mission en brouillon ou annulée : rien à planifier
    while d <= end:
        for r in reqs:
            if (r.valid_from and d < r.valid_from) or (r.valid_to and d > r.valid_to):
                continue
            days_ok = (d.isoformat() in (r.dates or [])) if r.dates else (d.weekday() in (r.weekdays or []))
            if not days_ok:
                continue
            # jours de fonctionnement des marques : contrainte dure (une mission client fixe ses propres jours)
            if r.mission_id is None and any(brands.get(b) and brands[b].active_weekdays and d.weekday() not in brands[b].active_weekdays
                                            for b in r.allocations):
                continue
            t = templates[r.template_id]
            h = shift_hours(d, t.start_time, t.end_time, t.break_minutes)
            for k in range(max(1, r.headcount or 1)):  # une personne par shift : « N personnes » = N shifts identiques
                slots.append(Slot(
                    f"{r.code}{'' if k == 0 else f'#{k + 1}'}|{d.isoformat()}", d, r.site_code, t.start_time, t.end_time, t.break_minutes,
                    split_allocation(h.effective_minutes, {b: float(v) for b, v in r.allocations.items()}),
                    tag=t.tag, template_id=t.code, required_skills=tuple(r.required_skills or ()),
                    mandatory=r.mandatory, day_group=f"{r.flex_group}|{d.isoformat()}" if r.flex_group else None,
                    stagger_group=r.stagger_group, priority=r.priority or 3, mission=missions[r.mission_id].code if r.mission_id else None))
        d += timedelta(days=1)

    slots += manual_slots(db, period)
    skills = {s.id: s.code for s in db.scalars(select(m.Skill))}
    emp_skills: Dict[uuid.UUID, set] = defaultdict(set)
    for es in db.scalars(select(m.EmployeeSkill)):
        if es.valid_until is None or es.valid_until >= end:  # certification échue pendant le mois : plus admise pour ce mois
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
    relationships = list(db.scalars(select(m.RelationshipPreference)))
    rel = {r.employee_id: r.other_employee_id for r in relationships if r.kind == "opposite_shifts"}
    for a_, b_ in list(rel.items()):  # une relation saisie dans un seul sens vaut pour les deux collaborateurs
        rel.setdefault(b_, a_)
    codes = {e.id: e.code for e in db.scalars(select(m.Employee))}
    # collaborateurs supprimés : seulement s'ils ont des affectations dans ce planning (historique), et plus aucun shift après leur retrait
    in_plan = set(db.scalars(select(m.Assignment.employee_id).where(m.Assignment.period_id == pid))) if pid else set()

    month_params = {p.employee_id: p for p in db.scalars(select(m.EmployeeMonthParams).where(
        m.EmployeeMonthParams.month == start.replace(day=1)))}
    roster_rows = list(db.scalars(select(m.PeriodEmployee).where(m.PeriodEmployee.period_id == pid))) if pid else []
    roster_out = {x.employee_id for x in roster_rows if not x.included}
    roster_in = {x.employee_id for x in roster_rows if x.included}  # inclusion explicite dans l'effectif de ce mois
    all_contracts: Dict[uuid.UUID, list] = defaultdict(list)
    for c in db.scalars(select(m.EmploymentContract)):
        all_contracts[c.employee_id].append(c)
    # référentiel juridique : plafond hebdomadaire par régime (la version la plus récente en vigueur) ; aucun plafond n'est supposé
    weekly_rules: Dict[Optional[str], int] = {}
    for r in sorted((r for r in rules if r.code == "weekly_max_minutes" and r.scope == "tenant"), key=lambda r: r.version):
        weekly_rules[r.jurisdiction or None] = int(r.params["value"])
    emps: List[SEmployee] = []
    fiches: Dict[str, dict] = {}
    names: Dict[str, str] = {}
    rows = db.scalars(select(m.Employee).where(m.Employee.active.is_(True)).order_by(m.Employee.code))
    for e in rows:
        if e.deleted_at is not None and e.id not in in_plan:
            continue  # supprimé : retiré des prochaines planifications
        mp = month_params.get(e.id)  # le quota de dimanches est propre au mois ; à défaut, valeur historique de la fiche
        if mp is not None:
            quota, qmode = mp.sunday_quota, mp.sunday_mode
        elif e.sunday_quota_migrated_at is None:  # quota historique, pas encore reporté sur les mois
            quota, qmode = e.sunday_quota, e.sunday_mode or "max"
        else:
            quota, qmode = None, "max"
        ended = bool(all_contracts.get(e.id)) and all(c.end_date is not None and c.end_date < start for c in all_contracts[e.id])
        # 1) paramètres habituels (fiche, disponibilités récurrentes, contrat, préférences, relations)
        se = SEmployee(e.code, e.name, dict(e.brands or {}), skills={s for s in emp_skills[e.id] if s},
                       weight=e.allocation_weight,
                       max_days_count=e.max_days_count, max_days_period=e.max_days_period,
                       min_days_month=e.min_days_month, max_days_month=e.max_days_month,
                       time_pref=e.time_pref, time_pref_strict=e.time_pref_strict,
                       available_weekdays=set(avail[e.id]) if avail.get(e.id) else None,
                       unavailable_weekdays=set(unav_wd[e.id]),
                       opposite_of=codes.get(rel.get(e.id)) if e.id in rel else None,
                       relations=[Relation(r.kind, codes[r.other_employee_id], r.strict) for r in relationships
                                  if r.employee_id == e.id and r.kind != "opposite_shifts" and r.other_employee_id in codes])
        c = contracts.get(e.id)
        if c:
            se.contract = Contract(c.activity_rate, c.monthly_min_minutes, c.monthly_target_minutes,
                                   c.monthly_max_minutes, c.weekly_max_minutes, c.overtime_allowed, c.hourly_cost_cents)
        se.legal_weekly_max_minutes = _regime_value(weekly_rules, c.legal_regime if c else None)
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
            elif p.kind == "rest_weekdays":
                (se.rest_weekdays_hard if p.is_hard else se.rest_weekdays_soft).update(int(w) for w in P["weekdays"])
            elif p.kind == "sites":
                if p.is_hard:
                    se.allowed_sites = set(P["sites"])
                else:
                    se.preferred_sites |= set(P["sites"])
        fiches[e.code], names[e.code] = {**fiche_of(se), "contract_ended": ended}, e.name
        kept = frozen.get("employees", {}).get(e.code) if frozen else None
        if kept is not None:  # 2) paramètres conservés par le planning (fiche, disponibilités récurrentes, effectif)
            apply_fiche(se, kept)
            ended = kept.get("contract_ended", ended)
        # 3) données propres au mois, toujours lues en direct. Un collaborateur ajouté APRÈS la création du planning n'en fait pas partie,
        # sauf inclusion explicite dans l'effectif de ce mois (ou application des paramètres actuels) : jamais d'effet rétroactif
        added_later = bool(frozen) and kept is None and e.id not in roster_in
        se.excluded = e.id in roster_out or ended or added_later
        se.unavailable_dates = set(unav_dt[e.id])
        se.sunday_quota, se.sunday_mode = quota, qmode
        if mp is not None and mp.max_days_set:
            se.max_days_count, se.max_days_period = mp.max_days_count, mp.max_days_period
        if mp is not None and mp.days_set:
            se.min_days_month, se.max_days_month = mp.min_days, mp.max_days
        # suppression : retiré des NOUVELLES générations et des plannings créés après ; un planning existant garde son effectif
        # (ses affectations ne deviennent pas des incompatibilités rétroactives)
        if e.removed_on is not None and (kept is None or cfg_overrides.get("generation")):
            se.left_on = e.removed_on
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
        elif r.code == "weights_ui":  # pondérations personnalisées (Paramètres → Pondération de l'algorithme)
            cfg.weights.update(engine_weights(r.params.get("criteria"), r.params.get("advanced")))
            cfg.hierarchical = bool(r.params.get("hierarchical", True))
        elif r.code == "break_rules":
            cfg.break_rules = [(int(x["over_minutes"]), int(x["break_minutes"])) for x in r.params.get("rules", [])]
    current_cap = tenant_cap(db, getattr(period, "tenant_id", None))
    cfg.monthly_cap_minutes = current_cap
    if capture is not None:
        capture.update({"employees": fiches, "config": config_of(cfg), "names": names})
    if frozen:
        apply_config(cfg, frozen.get("config", {}))
    if cfg_overrides.get("cap") == "current":  # le plafond mensuel actuel s'applique à toute nouvelle génération et modification manuelle
        cfg.monthly_cap_minutes = current_cap
    for k, v in cfg_overrides.items():
        if k == "weights":
            cfg.weights.update({a: int(b) for a, b in v.items() if a in DEFAULT_WEIGHTS})
        elif k in ("time_limit_s", "workers", "strict_coverage", "seed"):
            setattr(cfg, k, v)
    if cfg_overrides.get("strategy") in STRATEGIES:  # simulation : mêmes règles, importance relative des critères modifiée
        cfg.weights = apply_strategy(cfg.weights, cfg_overrides["strategy"])

    budgets = [BrandBudget(b.brand_code, b.target_minutes, b.requirements_defined, strict=b.strict)
               for b in db.scalars(select(m.MonthlyBudget).where(
                   m.MonthlyBudget.month == start.replace(day=1)))]
    used = {r.template_id for r in reqs}
    hyp = [f"Horaire supposé NON VALIDÉ : modèle {t.code} {t.start_time:%H:%M}-{t.end_time:%H:%M}"
           f"{' — ' + t.hypothesis_note if t.hypothesis_note else ''}. À confirmer ou modifier (paramétrable)."
           for t in templates.values() if t.is_hypothesis and t.id in used]
    hyp += [r.params["text"] for r in rules if r.code == "hypothesis" and r.params.get("text")]  # hypothèses saisies par le tenant
    # horaires autorisés par boutique / marque (modèles de shifts à portée) -> contrôle et catégories matin/middle/soir
    allowed: Dict[str, list] = defaultdict(list)
    group_brands: Dict[str, list] = defaultdict(list)
    for b in brands.values():
        if b.group_code:
            group_brands[b.group_code].append(b.code)
    for t in templates.values():
        if not t.scope_code:
            continue
        keys = [t.scope_code] + (group_brands.get(t.scope_code, []) if t.scope_type == "group" else [])
        for k in keys:
            if (t.start_time, t.end_time) not in allowed[k]:
                allowed[k].append((t.start_time, t.end_time))
    site_starts = {k: sorted({a for a, _ in v}) for k, v in allowed.items() if "@" not in k}
    for k, v in allowed.items():  # horaires « marque@site » : comptent aussi parmi les horaires de la boutique (matin / soir)
        if "@" in k:
            site = k.split("@", 1)[1]
            site_starts[site] = sorted(set(site_starts.get(site, [])) | {a for a, _ in v})
    outside = _outside_shifts(db, period)
    inp = SolverInput(start, end, slots, emps, budgets, cfg, leaves_provided=bool(leaves), hypotheses=sorted(hyp),
                      outside_shifts=outside, history_provided=bool(outside), site_starts=site_starts,
                      allowed_times=dict(allowed))
    return inp


def _outside_shifts(db: Session, period: m.PlanningPeriod) -> List[OutsideShift]:
    """Shifts déjà planifiés dans les périodes voisines (±7 jours) : semaines à cheval, repos et jours consécutifs."""
    lo, hi = period.start_date - timedelta(days=7), period.end_date + timedelta(days=7)
    codes = {e.id: e.code for e in db.scalars(select(m.Employee))}
    rows = db.execute(
        select(m.Shift, m.Assignment).join(m.Assignment, m.Assignment.shift_id == m.Shift.id)
        .where(m.Shift.period_id != period.id, m.Shift.day >= lo, m.Shift.day <= hi)).all()
    return [OutsideShift(codes[a.employee_id], sh.day, sh.start_time, sh.end_time, sh.effective_minutes) for sh, a in rows
            if a.employee_id in codes and not (period.start_date <= sh.day <= period.end_date)]


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
    rows = list(db.scalars(select(m.Assignment).where(m.Assignment.period_id == period.id)))
    allocs: Dict[uuid.UUID, Dict[str, int]] = defaultdict(dict)
    if rows:
        for r in db.scalars(select(m.BrandAllocation).where(m.BrandAllocation.assignment_id.in_([a.id for a in rows]))):
            allocs[r.assignment_id][r.brand_code] = r.minutes
    for a in rows:
        sh = shifts[a.shift_id]
        s = slots.get(sh.slot_key)
        if s is None:
            continue
        h = s.hours
        out.append(SAssign(s.id, codes[a.employee_id], s.day, s.start, s.end, h.presence_minutes, h.break_minutes,
                           h.effective_minutes, allocs.get(a.id) or dict(s.allocations), a.locked))
    return out


def persist_result(db: Session, tenant_id, period: m.PlanningPeriod, inp: SolverInput, res, run_id) -> None:
    """Applique le résultat par différence : une affectation inchangée reste la même ligne (identifiant et imputations conservés),
    les verrouillées ne bougent jamais, seules les autres sont remplacées."""
    codes = {e.code: e.id for e in db.scalars(select(m.Employee))}
    shifts = {s.slot_key: s for s in db.scalars(select(m.Shift).where(m.Shift.period_id == period.id))}
    existing = list(db.scalars(select(m.Assignment).where(m.Assignment.period_id == period.id)))
    wanted = {a.slot_id: codes[a.employee_id] for a in res.assignments}
    by_id = {s.id: k for k, s in shifts.items()}
    keep = set()
    for a in existing:
        if a.locked or wanted.get(by_id.get(a.shift_id)) == a.employee_id:
            keep.add(a.shift_id)
            if not a.locked:
                a.run_id = run_id
        else:
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


def brand_schedules(db: Session) -> Dict[str, list]:
    """Horaires autorisés PAR MARQUE : modèles dont la portée est la boutique de la marque, la marque ou son groupe."""
    brand_sites: Dict[str, list] = defaultdict(list)
    for r in db.scalars(select(m.StaffingRequirement)):
        for b in r.allocations:
            if r.site_code not in brand_sites[b]:
                brand_sites[b].append(r.site_code)
    templates = list(db.scalars(select(m.ShiftTemplate).order_by(m.ShiftTemplate.start_time)))
    out: Dict[str, list] = {}
    for b in db.scalars(select(m.Brand)):
        sites = brand_sites.get(b.code, [])
        keys = set(sites) | {b.code} | ({b.group_code} if b.group_code else set()) | {f"{b.code}@{x}" for x in sites}
        seen, lst = set(), []
        for t in templates:
            if t.scope_code in keys and (t.start_time, t.end_time) not in seen:
                seen.add((t.start_time, t.end_time))
                site = t.scope_code if t.scope_type == "site" else t.scope_code.split("@", 1)[1] if t.scope_type == "pair" else (sites[0] if sites else b.code)
                lst.append({"template_id": str(t.id), "template": t.code, "start": t.start_time.isoformat(), "end": t.end_time.isoformat(),
                            "break_minutes": t.break_minutes, "site": site})
        out[b.code] = lst
    return out


def manual_slots(db: Session, period: m.PlanningPeriod) -> List[Slot]:
    """Shifts ajoutés à la main : repris comme créneaux (verrouillés) pour que le moteur et le vérificateur les prennent en compte."""
    out = []
    shifts = list(db.scalars(select(m.Shift).where(m.Shift.period_id == period.id, m.Shift.slot_key.like("MANUAL|%"))))
    if not shifts:
        return out
    alloc: Dict[uuid.UUID, Dict[str, int]] = defaultdict(dict)
    for a, r in db.execute(select(m.Assignment, m.BrandAllocation).join(m.BrandAllocation, m.BrandAllocation.assignment_id == m.Assignment.id)
                           .where(m.Assignment.period_id == period.id)).all():
        alloc[a.shift_id][r.brand_code] = r.minutes
    for sh in shifts:
        if alloc.get(sh.id):
            out.append(Slot(sh.slot_key, sh.day, sh.site_code, sh.start_time, sh.end_time, sh.break_minutes, dict(alloc[sh.id]),
                            tag="day", template_id="manual", mandatory=False))
    return out
