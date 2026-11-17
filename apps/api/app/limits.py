"""Plafond mensuel d'heures de l'entreprise (règle interne, pas une valeur légale), appliqué à TOUTE modification manuelle.

Le total compte le travail effectif de tous les shifts du collaborateur dans le mois civil, tous sites et toutes marques cumulés.
Une modification est refusée si elle porte un collaborateur au-delà du plafond ; une modification qui réduit ses heures reste permise
(un planning établi avant l'activation du plafond peut ainsi être corrigé)."""
from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date
from typing import Dict, Iterable, Optional, Tuple

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from planning_solver.model import fmt_minutes, month_label

from . import models as m
from .services_bridge import tenant_cap

Key = Tuple[uuid.UUID, Tuple[int, int]]


def month_minutes(db: Session, employee_ids: Iterable[uuid.UUID], months: Iterable[Tuple[int, int]]) -> Dict[Key, int]:
    ids, keys = list({e for e in employee_ids if e}), sorted(set(months))
    out: Dict[Key, int] = defaultdict(int)
    if not ids or not keys:
        return out
    lo = date(keys[0][0], keys[0][1], 1)
    y, mo = keys[-1]
    hi = date(y + (mo == 12), mo % 12 + 1, 1)
    rows = db.execute(select(m.Assignment.employee_id, m.Shift.day, m.Shift.effective_minutes)
                      .join(m.Shift, m.Shift.id == m.Assignment.shift_id)
                      .where(m.Assignment.employee_id.in_(ids), m.Shift.day >= lo, m.Shift.day < hi)).all()
    for eid, day, mins in rows:
        if (day.year, day.month) in keys:
            out[eid, (day.year, day.month)] += mins or 0
    return out


def guard_monthly_cap(db: Session, tenant_id, before: Dict[Key, int], employee_ids: Iterable[uuid.UUID],
                      months: Iterable[Tuple[int, int]], cap: Optional[int] = None) -> None:
    """À appeler APRÈS la modification (flush) : 409 si un collaborateur dépasse le plafond et que ses heures ont augmenté.
    L'exception annule toute la transaction : rien n'est enregistré."""
    cap = tenant_cap(db, tenant_id) if cap is None else cap
    if cap is None:
        return
    db.flush()
    after = month_minutes(db, employee_ids, months)
    bad = [(k, v) for k, v in after.items() if v > cap and v > before.get(k, 0)]
    if not bad:
        return
    names = {e.id: e.name for e in db.scalars(select(m.Employee).where(m.Employee.id.in_([k[0] for k, _ in bad])))}
    issues = [{"code": "MONTHLY_CAP", "level": "blocking", "rule": "Plafond mensuel d'heures (règle de l'entreprise)", "limit": fmt_minutes(cap),
               "reached": fmt_minutes(v), "employee": names.get(k[0], "—"),
               "message": f"{names.get(k[0], 'Ce collaborateur')} aurait {fmt_minutes(v)} de travail effectif en {month_label(*k[1])}, "
                          f"tous sites et marques cumulés, pour un plafond de {fmt_minutes(cap)}."} for k, v in bad]
    raise HTTPException(409, detail={"code": "monthly_cap", "can_override": False, "issues": issues,
                                     "message": "Modification refusée : plafond mensuel de " + fmt_minutes(cap) + " dépassé. " + " ".join(i["message"] for i in issues)})


def days_settings_error(db: Session, tenant_id, brands: dict, min_days: Optional[int], max_days: Optional[int],
                        n_days: int = 31, period_label: str = "un mois") -> Optional[str]:
    """Contrôle d'un couple minimum / maximum de jours par mois ; None si cohérent, sinon l'explication précise du blocage."""
    for v, lab in ((min_days, "minimum"), (max_days, "maximum")):
        if v is not None and not 1 <= v <= n_days:
            return f"Le {lab} de jours doit être compris entre 1 et {n_days} ({period_label} compte {n_days} jours)."
    if min_days is not None and max_days is not None and min_days > max_days:
        return f"Le minimum ({min_days} jours) dépasse le maximum ({max_days} jours) : corrigez l'un des deux."
    cap = tenant_cap(db, tenant_id)
    if min_days is None or cap is None or not brands:
        return None
    from .services_bridge import brand_schedules
    from planning_solver.timecalc import shift_hours
    from datetime import time as _time
    shortest = None
    sched = brand_schedules(db)
    for b in brands:
        for t in sched.get(b, []):
            mins = shift_hours(date(2026, 1, 5), _time.fromisoformat(t["start"]), _time.fromisoformat(t["end"]), t["break_minutes"]).effective_minutes
            shortest = mins if shortest is None else min(shortest, mins)
    if shortest and min_days * shortest > cap:
        return (f"Avec des shifts d'au moins {fmt_minutes(shortest)} de travail effectif (horaires des marques autorisées), {min_days} jours "
                f"représentent au moins {fmt_minutes(min_days * shortest)}, au-delà du plafond mensuel de {fmt_minutes(cap)}. "
                f"Minimum possible : {cap // shortest} jours.")
    return None
