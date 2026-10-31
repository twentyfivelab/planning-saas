"""Compteur des dimanches : calculé à partir des vrais shifts de la période et des quotas des collaborateurs."""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from typing import Dict, List, Optional

from .model import Assignment, SolverInput


def sundays_in(inp: SolverInput) -> list:
    d, out = inp.period_start, []
    while d <= inp.period_end:
        if d.weekday() == 6:
            out.append(d)
        d += timedelta(days=1)
    return out


def sunday_summary(inp: SolverInput, assignments: Optional[List[Assignment]] = None) -> Dict[str, object]:
    """total = shifts obligatoires un dimanche ; réservés = quotas « objectif exact » ; planifiés = affectations réelles.

    - remaining_to_reserve = total - réservés (ce que les quotas ne couvrent pas encore) ;
    - unplanned = total - planifiés (shifts du dimanche sans collaborateur).
    Les quotas « maximum » ne réservent rien : ils plafonnent seulement (capacité). Rien n'est compté deux fois."""
    sundays = sundays_in(inp)
    slots = [s for s in inp.slots if s.mandatory and s.day.weekday() == 6]
    by_site: Dict[str, int] = defaultdict(int)
    by_day: Dict[str, int] = defaultdict(int)
    for s in slots:
        by_site[s.site] += 1
        by_day[s.day.isoformat()] += 1
    total = len(slots)
    n_sun = len(sundays)
    reserved, capacity, flexible = 0, 0, 0
    employees: Dict[str, dict] = {}
    slot_ids = {s.id for s in slots}
    planned_by: Dict[str, int] = defaultdict(int)
    planned = 0
    for a in assignments or []:
        if a.slot_id in slot_ids:
            planned += 1
            planned_by[a.employee_id] += 1
    for e in inp.employees:
        q = e.sunday_quota
        available = sum(1 for d in sundays if not e.blocked(d))
        info = {"name": e.name, "quota": q, "mode": e.sunday_mode if q is not None else None,
                "available_sundays": available, "planned": planned_by.get(e.id, 0), "warnings": []}
        if q is None:
            flexible += 1
        else:
            eff = min(q, n_sun)
            if e.sunday_mode == "exact":
                reserved += eff
            capacity += eff
            if q > n_sun:
                info["warnings"].append(f"Quota de {q} dimanche(s) supérieur au nombre de dimanches de la période ({n_sun}).")
            if q > available:
                info["warnings"].append(f"Seulement {available} dimanche(s) disponible(s) pour {q} demandé(s).")
        employees[e.id] = info
    remaining_to_reserve = max(0, total - reserved)
    alerts: List[dict] = []
    if remaining_to_reserve > 0:
        if flexible == 0 and capacity < total:
            alerts.append({"level": "warning", "text": f"{total - capacity} shift(s) du dimanche ne peuvent être couverts : tous les collaborateurs ont un quota et la capacité cumulée est de {capacity} pour {total} shifts."})
        else:
            alerts.append({"level": "info", "text": f"{remaining_to_reserve} shift(s) du dimanche restent à distribuer : le moteur les répartira entre les collaborateurs sans quota exact."})
    if reserved > total:
        alerts.append({"level": "warning", "text": f"Les quotas réservés ({reserved}) dépassent les {total} shifts du dimanche."})
    if assignments is not None and total - planned > 0:
        alerts.append({"level": "warning", "text": f"{total - planned} shift(s) du dimanche non planifié(s)."})
    return {"sundays": [d.isoformat() for d in sundays], "per_sunday": (total // n_sun) if n_sun else 0,
            "total": total, "by_site": dict(by_site), "by_day": dict(by_day), "reserved": reserved, "capacity_max": capacity,
            "planned": planned, "remaining_to_reserve": remaining_to_reserve, "unplanned": total - planned,
            "flexible_employees": flexible, "employees": employees, "alerts": alerts}
