"""Vérificateur indépendant des contraintes dures (ne dépend pas de CP-SAT)."""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from typing import Dict, List

from .model import Assignment, SolverInput


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
            if e.blocked(s.day):
                out.append(f"UNAVAILABLE: {e.name} le {s.day}")
            if s.tag in e.forbidden_tags:
                out.append(f"FORBIDDEN_TAG: {e.name} sur {s.id} ({s.tag})")
            if any(b not in e.brands for b in s.brands):
                out.append(f"BRAND_NOT_ELIGIBLE: {e.name} sur {s.id}")
            if any(k not in e.skills for k in s.required_skills):
                out.append(f"SKILL_MISSING: {e.name} sur {s.id}")
        for p, q in zip(lst, lst[1:]):
            ep = slots[p.slot_id].bounds[1]
            sq = slots[q.slot_id].bounds[0]
            if sq < ep:
                out.append(f"OVERLAP: {e.name} {p.slot_id} / {q.slot_id}")
            elif sq - ep < timedelta(hours=cfg.rest_hours):
                out.append(f"REST<{cfg.rest_hours}h: {e.name} {p.slot_id} -> {q.slot_id}")
        days = sorted({a.day for a in lst})
        run = e.prior_consecutive_days
        prev = None
        for d in days:
            run = run + 1 if prev is not None and d - prev == timedelta(days=1) else (
                e.prior_consecutive_days + 1 if prev is None and d == inp.period_start else 1)
            if run > cfg.max_consecutive_days:
                out.append(f"CONSECUTIVE>{cfg.max_consecutive_days}: {e.name} jusqu'au {d}")
            prev = d
        weeks: Dict[tuple, int] = defaultdict(int)
        wmin: Dict[tuple, int] = defaultdict(int)
        for d in days:
            weeks[d.isocalendar()[:2]] += 1
        for a in lst:
            wmin[a.day.isocalendar()[:2]] += a.effective_minutes
        if e.max_days_per_week is not None:
            for w, n in weeks.items():
                if n > e.max_days_per_week:
                    out.append(f"MAX_DAYS_WEEK: {e.name} {n}>{e.max_days_per_week} semaine {w}")
        c = e.contract
        if c and c.weekly_max_minutes is not None:
            for w, m in wmin.items():
                if m > c.weekly_max_minutes:
                    out.append(f"CONTRACT_WEEKLY_MAX: {e.name} semaine {w}")
        if c and c.monthly_max_minutes is not None and not c.overtime_allowed:
            if sum(a.effective_minutes for a in lst) > c.monthly_max_minutes:
                out.append(f"CONTRACT_MONTHLY_MAX: {e.name}")
        if e.weekly_rest_days_hard and e.weekly_rest_days_pref is not None:
            for w, n in weeks.items():
                if n > 7 - e.weekly_rest_days_pref and _full_week(inp, w):
                    out.append(f"REST_DAYS_HARD: {e.name} semaine {w}")

    planned: Dict[str, int] = defaultdict(int)
    for a in assignments:
        for b, m in a.allocations.items():
            planned[b] += m
    for b in inp.budgets:
        if planned[b.brand] > b.target_minutes:
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
