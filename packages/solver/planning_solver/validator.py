"""Vérificateur indépendant des contraintes dures (ne dépend pas de CP-SAT)."""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from typing import Dict, List

from .context import required_break
from .model import Assignment, SolverInput, slot_category, site_start_times
from .sundays import sundays_in
from .timecalc import shift_bounds, shift_hours


def validate(inp: SolverInput, assignments: List[Assignment]) -> List[str]:
    slots = {s.id: s for s in inp.slots}
    emps = {e.id: e for e in inp.employees}
    cfg = inp.config
    out: List[str] = []

    per_slot: Dict[str, List[str]] = defaultdict(list)
    per_emp: Dict[str, List[Assignment]] = defaultdict(list)
    for a in assignments:
        per_slot[a.slot_id].append(a.employee_id)
        per_emp[a.employee_id].append(a)
    for sid, es in per_slot.items():
        if len(es) > 1:
            out.append(f"DOUBLE_ASSIGNMENT: {sid} pourvu par {es}")

    for sid, eid in inp.locked.items():
        if not any(a.slot_id == sid and a.employee_id == eid for a in assignments):
            out.append(f"LOCK_VIOLATED: {sid} devait rester à {eid}")

    out += [f"FROZEN_SLOT: {sid} hors du périmètre de la réoptimisation" for sid in per_slot if sid in inp.frozen_empty]

    group_count: Dict[str, int] = defaultdict(int)
    for a in assignments:
        s = slots[a.slot_id]
        if s.day_group:
            group_count[s.day_group] += 1
    out += [f"DAY_GROUP: {g} rempli {n} fois" for g, n in group_count.items() if n > 1]

    for eid, lst in per_emp.items():
        e = emps[eid]
        lst.sort(key=lambda a: slots[a.slot_id].bounds[0])
        for a in lst:
            s = slots[a.slot_id]
            if e.excluded:
                out.append(f"EXCLUDED_FROM_PERIOD: {e.name} sur {a.slot_id} (hors de l'effectif du mois)")
            elif e.blocked(s.day):
                out.append(f"UNAVAILABLE: {e.name} le {s.day} sur {a.slot_id}")
            if s.tag in e.forbidden_tags:
                out.append(f"FORBIDDEN_TAG: {e.name} sur {s.id} ({s.tag})")
            if any(b not in e.brands for b in s.brands):
                out.append(f"BRAND_NOT_ELIGIBLE: {e.name} sur {s.id}")
            if any(k not in e.skills for k in s.required_skills):
                out.append(f"SKILL_MISSING: {e.name} sur {s.id}")
            if s.day.weekday() in e.rest_weekdays_hard:
                out.append(f"REST_WEEKDAY: {e.name} sur {s.id} (jour de repos obligatoire)")
            if e.allowed_sites is not None and s.site not in e.allowed_sites:
                out.append(f"SITE_NOT_ALLOWED: {e.name} sur {s.id} ({s.site} hors de ses sites autorisés)")
            h = shift_hours(s.day, s.start, s.end, s.break_minutes)  # heures recalculées indépendamment du moteur
            if (a.presence_minutes, a.break_minutes, a.effective_minutes) != (h.presence_minutes, h.break_minutes, h.effective_minutes):
                out.append(f"HOURS_MISMATCH: {a.slot_id} {a.effective_minutes} min enregistrées, {h.effective_minutes} recalculées")
            if a.allocations and sum(a.allocations.values()) != a.effective_minutes:
                out.append(f"ALLOCATION_MISMATCH: {a.slot_id} imputations {sum(a.allocations.values())} min pour {a.effective_minutes} min effectives")
            need = required_break(cfg.break_rules, s)
            if s.break_minutes < need:
                out.append(f"BREAK_TOO_SHORT: {a.slot_id} pause de {s.break_minutes} min pour {need} min exigées")
        for p, q in zip(lst, lst[1:]):
            ep = slots[p.slot_id].bounds[1]
            sq = slots[q.slot_id].bounds[0]
            if sq < ep:
                out.append(f"OVERLAP: {e.name} {p.slot_id} / {q.slot_id}")
            elif sq - ep < timedelta(hours=cfg.rest_hours):
                out.append(f"REST<{cfg.rest_hours}h: {e.name} {p.slot_id} -> {q.slot_id}")
        days = sorted({a.day for a in lst})
        # jours travaillés hors période (périodes voisines) : semaines à cheval, jours consécutifs, repos à la frontière
        out_days = {o.day for o in inp.outside_shifts if o.employee_id == eid and not (inp.period_start <= o.day <= inp.period_end)}
        out_days |= {inp.period_start - timedelta(days=k) for k in range(1, e.prior_consecutive_days + 1)}
        all_days = sorted(set(days) | out_days)
        run, prev = 0, None
        for d in all_days:
            run = run + 1 if prev is not None and d - prev == timedelta(days=1) else 1
            if run > cfg.max_consecutive_days and d in days:
                out.append(f"CONSECUTIVE>{cfg.max_consecutive_days}: {e.name} jusqu'au {d}")
            prev = d
        for o in (o for o in inp.outside_shifts if o.employee_id == eid):
            o0, o1 = shift_bounds(o.day, o.start, o.end)
            for a in lst:
                s0, s1 = slots[a.slot_id].bounds
                if o0 < s1 + timedelta(hours=cfg.rest_hours) and s0 < o1 + timedelta(hours=cfg.rest_hours):
                    out.append(f"REST<{cfg.rest_hours}h: {e.name} {a.slot_id} avec un shift du {o.day} (période voisine)")
        weeks: Dict[tuple, int] = defaultdict(int)
        for d in set(days) | out_days:
            weeks[d.isocalendar()[:2]] += 1
        wmin: Dict[tuple, int] = defaultdict(int)
        for a in lst:
            wmin[a.day.isocalendar()[:2]] += a.effective_minutes
        wplanned = set(wmin)
        for o in inp.outside_shifts:
            if o.employee_id == eid:
                wmin[o.day.isocalendar()[:2]] += o.minutes  # heures d'une période voisine dans la même semaine
        week_cap = e.max_days_per_week
        if e.max_days_count is not None and e.max_days_period == "week":
            week_cap = e.max_days_count if week_cap is None else min(week_cap, e.max_days_count)
        if week_cap is not None:
            for w, n in weeks.items():
                if n > week_cap and any(d.isocalendar()[:2] == w for d in days):
                    out.append(f"MAX_DAYS_WEEK: {e.name} {n}>{week_cap} semaine {w}")
        if e.max_days_count is not None and e.max_days_period == "month" and len(days) > e.max_days_count:
            out.append(f"MAX_DAYS_MONTH: {e.name} {len(days)}>{e.max_days_count} jours sur la période")
        if e.sunday_quota is not None:
            n_sun = sum(1 for d in days if d.weekday() == 6)
            if n_sun > min(e.sunday_quota, len(sundays_in(inp))):
                out.append(f"SUNDAY_QUOTA: {e.name} {n_sun}>{e.sunday_quota} dimanche(s)")
        if e.time_pref and e.time_pref_strict:
            starts = site_start_times(inp)
            for a in lst:
                cat = slot_category(slots[a.slot_id], starts)
                if cat is not None and cat != e.time_pref:
                    out.append(f"TIME_PREF_STRICT: {e.name} sur {a.slot_id} ({cat}, préférence {e.time_pref} obligatoire)")
        c = e.contract
        if c and c.weekly_max_minutes is not None:
            for w, m in wmin.items():
                if w in wplanned and m > c.weekly_max_minutes:
                    out.append(f"CONTRACT_WEEKLY_MAX: {e.name} semaine {w}")
        if e.legal_weekly_max_minutes is not None:
            for w, m in wmin.items():
                if w in wplanned and m > e.legal_weekly_max_minutes:
                    out.append(f"LEGAL_WEEKLY_MAX: {e.name} {m}>{e.legal_weekly_max_minutes} minutes semaine {w}")
        if c and c.monthly_max_minutes is not None and not c.overtime_allowed:
            if sum(a.effective_minutes for a in lst) > c.monthly_max_minutes:
                out.append(f"CONTRACT_MONTHLY_MAX: {e.name}")
        if e.weekly_rest_days_hard and e.weekly_rest_days_pref is not None:
            for w, n in weeks.items():
                if n > 7 - e.weekly_rest_days_pref and _full_week(inp, w):
                    out.append(f"REST_DAYS_HARD: {e.name} semaine {w}")

    # relations strictes entre collaborateurs (même jour, même site)
    where = {eid: {(slots[a.slot_id].day, slots[a.slot_id].site) for a in lst} for eid, lst in per_emp.items()}
    for eid, lst in per_emp.items():
        e = emps[eid]
        tutors = [r for r in e.relations if r.kind == "mentor" and r.strict and r.other in emps]
        for at in sorted(where[eid]):
            if tutors and not any(at in where.get(r.other, ()) for r in tutors):
                out.append(f"MENTOR_MISSING: {e.name} le {at[0]} à {at[1]} sans tuteur présent")
            for r in e.relations:
                if r.kind == "avoid_together" and r.strict and at in where.get(r.other, ()) and (eid < r.other or not any(
                        x.kind == r.kind and x.other == eid and x.strict for x in emps[r.other].relations)):
                    out.append(f"RELATION_AVOID: {e.name} et {emps[r.other].name} le {at[0]} à {at[1]}")

    if inp.allowed_times:
        for a in assignments:
            sl = slots[a.slot_id]
            scopes = [k for k in [sl.site, *sl.brands, *(f"{b}@{sl.site}" for b in sl.brands)] if k in inp.allowed_times]
            if scopes and not any((sl.start, sl.end) in inp.allowed_times[k] for k in scopes):
                out.append(f"SCHEDULE_NOT_ALLOWED: {a.slot_id} {sl.start:%H:%M}-{sl.end:%H:%M} hors horaires autorisés ({sl.site})")
    planned: Dict[str, int] = defaultdict(int)
    for a in assignments:
        for b, m in a.allocations.items():
            planned[b] += m
    for b in inp.budgets:
        if b.strict and planned[b.brand] > b.target_minutes:
            out.append(f"BUDGET_EXCEEDED: {b.brand} {planned[b.brand]}>{b.target_minutes}")
    return out


def _full_week(inp: SolverInput, week: tuple) -> bool:
    d = inp.period_start
    n = 0
    while d <= inp.period_end:
        if d.isocalendar()[:2] == week:
            n += 1
        d += timedelta(days=1)
    return n == 7
