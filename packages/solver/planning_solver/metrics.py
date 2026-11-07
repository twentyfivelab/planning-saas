"""Indicateurs d'un planning, recalculés à partir des affectations (sans le solveur) : couverture, atteinte des objectifs horaires,
dimanches, ouvertures et fermetures, jours consécutifs, préférences non satisfaites, coût estimé, modifications par rapport à un
planning de référence. Mêmes indicateurs pour le planning courant, une simulation ou le tableau de bord."""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, Iterable, List, Optional

from .context import Prepared, period_of, prepare, preference_checks
from .model import Assignment, SolverInput
from .objective import Evaluator


def _longest_run(days: Iterable) -> int:
    best = run = 0
    prev = None
    for d in sorted(days):
        run = run + 1 if prev is not None and (d - prev).days == 1 else 1
        best, prev = max(best, run), d
    return best


def plan_metrics(inp: SolverInput, assignments: List[Assignment], prep: Optional[Prepared] = None,
                 reference: Optional[Dict[str, str]] = None) -> Dict[str, object]:
    """`reference` : {slot: collaborateur} du planning de comparaison (nombre de modifications)."""
    prep = prep or prepare(inp)
    slots, emps = prep.slots, prep.emps
    mine: Dict[str, List[Assignment]] = defaultdict(list)
    filled = set()
    for a in assignments:
        if a.slot_id in slots:
            mine[a.employee_id].append(a)
            filled.add(a.slot_id)
    mandatory = [s for s in inp.slots if s.mandatory]
    uncovered = [s for s in mandatory if s.id not in filled]
    soft: Dict[str, int] = defaultdict(int)
    rows, by_brand, by_site = [], defaultdict(int), defaultdict(int)
    cost_cents, cost_known, total = 0, 0, 0
    sundays: List[int] = []
    for e in inp.employees:
        lst = mine.get(e.id, [])
        minutes = sum(a.effective_minutes for a in lst)
        total += minutes
        days = {a.day for a in lst}
        sl = [slots[a.slot_id] for a in lst]
        c = e.contract
        contract_target = c.monthly_target_minutes if c else None
        target = contract_target if contract_target else prep.targets.get(e.id, 0)
        for a in lst:
            for b, mi in a.allocations.items():
                by_brand[b] += mi
            by_site[slots[a.slot_id].site] += a.effective_minutes
            if c is not None and c.hourly_cost_cents is not None:
                cost_cents += round(a.effective_minutes * c.hourly_cost_cents / 60)
                cost_known += a.effective_minutes
        for s in sl:
            for _code, ok, _f in preference_checks(e, s):
                if not ok:
                    soft["preferences"] += 1
            if e.time_pref and not e.time_pref_strict and prep.category[s.id] not in (None, e.time_pref):
                soft["preferences_horaires"] += 1
            if any(e.brands.get(b) == "reinforce" for b in s.brands):
                soft["renforts"] += 1
        n_sun = sum(1 for d in prep.suns if d in days)
        if not e.excluded:
            sundays.append(n_sun)
        if e.sunday_quota and e.sunday_mode == "exact" and n_sun < min(e.sunday_quota, len(prep.suns)):
            soft["quotas_dimanches_non_atteints"] += 1
        rows.append({"id": e.id, "name": e.name, "minutes": minutes, "target_minutes": target, "contract_target": contract_target is not None,
                     "gap_minutes": minutes - target, "attainment": round(100 * minutes / target, 1) if target else None,
                     "days": len(days), "sundays": n_sun, "opens": sum(1 for s in sl if s.tag == "open"), "closes": sum(1 for s in sl if s.tag == "close"),
                     "max_consecutive": _longest_run(days), "sites": len({s.site for s in sl}), "excluded": e.excluded})
    for e in inp.employees:
        if e.opposite_of and e.id < e.opposite_of and e.opposite_of in emps:
            a = {(x.day, period_of(slots[x.slot_id])) for x in mine.get(e.id, [])}
            b = {(x.day, period_of(slots[x.slot_id])) for x in mine.get(e.opposite_of, [])}
            soft["horaires_opposes"] += len(a & b)
    active = [r for r in rows if not r["excluded"]]
    out: Dict[str, object] = {
        "mandatory_shifts": len(mandatory), "covered_shifts": len(mandatory) - len(uncovered), "uncovered_shifts": len(uncovered),
        "coverage_rate": round(100 * (len(mandatory) - len(uncovered)) / len(mandatory), 2) if mandatory else None,
        "uncovered_minutes": sum(s.effective_minutes for s in uncovered), "total_minutes": total,
        "assignments": len(filled), "gap_to_targets_minutes": sum(abs(r["gap_minutes"]) for r in active),
        "soft_unsatisfied": sum(soft.values()), "soft_detail": dict(soft),
        "sundays_min": min(sundays, default=0), "sundays_max": max(sundays, default=0), "sundays_total": sum(sundays),
        "max_consecutive": max((r["max_consecutive"] for r in active), default=0),
        "cost_cents": cost_cents if cost_known else None, "cost_known_share": round(100 * cost_known / total, 1) if total else None,
        "by_brand": dict(by_brand), "by_site": dict(by_site), "employees": rows,
        "objective": Evaluator(inp, assignments, prep).terms(),
    }
    if reference is not None:
        now = {a.slot_id: a.employee_id for a in assignments if a.slot_id in slots}
        added = sum(1 for k in now if k not in reference)
        removed = sum(1 for k in reference if k not in now)
        changed = sum(1 for k, v in now.items() if k in reference and reference[k] != v)
        out["changes"] = {"added": added, "removed": removed, "changed": changed, "total": added + removed + changed,
                          "unchanged": sum(1 for k, v in now.items() if reference.get(k) == v)}
    return out
