"""Classement algorithmique des remplaçants d'un shift : chaque candidat est contrôlé par le vérificateur indépendant (contraintes
dures), puis classé selon la variation RÉELLE de la fonction objectif du moteur s'il prenait ce shift (mêmes critères, mêmes poids).
Aucune note arbitraire : le score n'est que ce coût ramené sur 0–100 entre le meilleur et le moins bon candidat compatible."""
from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional

from .context import Prepared, ineligibility, prepare
from .model import Assignment, SolverInput
from .objective import Evaluator
from .validator import validate

TERM_LABELS = {
    "coverage": "Couverture du shift", "budget": "Budget de la marque", "budget_over": "Dépassement de budget", "reinforce": "Niveau sur la marque",
    "preference": "Préférences individuelles", "time_pref": "Préférence horaire", "fairness": "Écart à l'objectif horaire", "overtime": "Heures au-delà de l'objectif contractuel",
    "site_change": "Changements de site", "balance": "Équilibre ouvertures / fermetures / week-ends", "fatigue": "Fatigue (5 jours d'affilée)", "family": "Relations entre collaborateurs",
    "stagger": "Prises de poste décalées", "rest_days": "Jours de repos souhaités", "stability": "Stabilité du planning", "sunday_quota": "Objectif de dimanches",
    "individual": "Priorité individuelle", "sunday_balance": "Équilibre des dimanches", "alternation": "Alternance matin / soir", "days_balance": "Équilibre des jours travaillés", "cost": "Coût estimé",
}
LEVEL_LABEL = {"priority": "Prioritaire", "secondary": "Secondaire", "reinforce": "Renfort"}
_GLOBAL_CODES = ("LOCK_VIOLATED", "DOUBLE_ASSIGNMENT", "BRAND_NOT_ELIGIBLE")  # déjà couverts par le préfiltrage ou propres au planning courant


def _new_assignment(s, employee_id: str, locked: bool = False) -> Assignment:
    h = s.hours
    return Assignment(s.id, employee_id, s.day, s.start, s.end, h.presence_minutes, h.break_minutes, h.effective_minutes, dict(s.allocations), locked)


def term_lines(delta: Dict[str, int]) -> List[dict]:
    """Détail lisible d'une variation de coût : du critère le plus pénalisant au plus favorable."""
    return [{"term": k, "label": TERM_LABELS.get(k, k), "points": v, "effect": "defavorable" if v > 0 else "favorable"}
            for k, v in sorted(delta.items(), key=lambda kv: -kv[1]) if v]


def rank_replacements(inp: SolverInput, assignments: List[Assignment], slot_id: str, prep: Optional[Prepared] = None,
                      exclude: Iterable[str] = ()) -> Dict[str, object]:
    prep = prep or prepare(inp)
    s = prep.slots[slot_id]
    ev = Evaluator(inp, assignments, prep)
    holder = ev.holder.get(slot_id)
    others = [a for a in assignments if a.slot_id != slot_id]
    before = set(validate(inp, others))
    minutes: Dict[str, int] = {}
    for a in assignments:
        minutes[a.employee_id] = minutes.get(a.employee_id, 0) + a.effective_minutes
    leave_uncovered = ev.delta(slot_id, None) if holder is not None else {}
    excluded = set(exclude) | ({holder} if holder else set())
    rows: List[dict] = []
    for e in inp.employees:
        if e.id in excluded:
            continue
        base = {"employee_id": e.id, "name": e.name, "brand_level": [e.brands.get(b) for b in s.brands],
                "brand_level_label": " + ".join(sorted({LEVEL_LABEL.get(e.brands.get(b), "Non autorisé·e") for b in s.brands})),
                "minutes": minutes.get(e.id, 0), "target_minutes": _target(prep, e.id),
                "after_minutes": minutes.get(e.id, 0) + s.effective_minutes, "skills_ok": all(k in e.skills for k in s.required_skills),
                "available": not e.blocked(s.day) and s.day.weekday() not in e.rest_weekdays_hard,
                "cost_cents": round(s.effective_minutes * e.contract.hourly_cost_cents / 60) if e.contract and e.contract.hourly_cost_cents is not None else None}
        reason = ineligibility(e, s, prep.starts_by_site)
        if reason is not None:
            rows.append({**base, "status": "impossible", "blocking": [{"code": reason[0], "message": reason[1]}], "delta_cost": None, "terms": [], "score": None})
            continue
        new = [v for v in validate(inp, [*others, _new_assignment(s, e.id)]) if v not in before and not v.startswith(_GLOBAL_CODES)]
        if new:
            rows.append({**base, "status": "impossible", "blocking": [{"code": re.match(r"[A-Z_<>0-9]+", v).group(0), "message": v.split(": ", 1)[-1]} for v in new],
                         "delta_cost": None, "terms": [], "score": None})
            continue
        delta = ev.delta(slot_id, e.id)
        rows.append({**base, "status": "compatible", "blocking": [], "delta_cost": sum(delta.values()), "terms": term_lines(delta), "score": None})
    ok = [r for r in rows if r["status"] == "compatible"]
    if ok:
        lo, hi = min(r["delta_cost"] for r in ok), max(r["delta_cost"] for r in ok)
        for r in ok:
            r["score"] = 100 if hi == lo else round(100 * (hi - r["delta_cost"]) / (hi - lo))
    rows.sort(key=lambda r: (r["status"] != "compatible", r["delta_cost"] if r["delta_cost"] is not None else 0, r["name"]))
    return {"slot_id": slot_id, "holder": holder, "candidates": rows, "compatible": len(ok),
            "cost_if_uncovered": sum(leave_uncovered.values()) if holder is not None else None}


def _target(prep: Prepared, eid: str) -> int:
    c = prep.emps[eid].contract
    return c.monthly_target_minutes if c and c.monthly_target_minutes else prep.targets.get(eid, 0)
