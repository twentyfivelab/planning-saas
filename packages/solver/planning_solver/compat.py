"""Compatibilité d'un planning existant avec les paramètres ACTUELS des collaborateurs (sans rien modifier)."""
from __future__ import annotations

from typing import Dict, List

from .model import Assignment, CATEGORY_LABEL, SolverInput, site_start_times, slot_category
from .validator import validate


def compatibility(inp: SolverInput, assignments: List[Assignment]) -> Dict[str, object]:
    """hard = violations de contraintes dures (indisponibilité, marque non autorisée, préférence stricte, quotas, limites de jours,
    horaires non autorisés, repos…) ; soft = préférences souples non respectées (préférence horaire). Lecture seule."""
    hard = validate(inp, assignments)
    slots = {s.id: s for s in inp.slots}
    emps = {e.id: e for e in inp.employees}
    starts = site_start_times(inp)
    soft: List[dict] = []
    for a in assignments:
        e, s = emps.get(a.employee_id), slots.get(a.slot_id)
        if e is None or s is None or not e.time_pref or e.time_pref_strict:
            continue
        cat = slot_category(s, starts)
        if cat is not None and cat != e.time_pref:
            soft.append({"slot_id": a.slot_id, "employee": e.name, "kind": "time_pref",
                         "text": f"{e.name} : préférence « {CATEGORY_LABEL[e.time_pref]} » non respectée sur {a.slot_id} ({CATEGORY_LABEL[cat].lower()})."})
    return {"hard": hard, "soft": soft, "checked": len(assignments)}
