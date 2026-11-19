"""Couverture des besoins d'une marque pour le planning d'un mois (suivi de l'ajout manuel d'une marque) et état qui en découle."""
from sqlalchemy import select

from planning_solver.validator import violations

from . import models as m
from .services_bridge import assignments_for_validation, build_input


def brand_coverage(db, p: m.PlanningPeriod, code: str, inp=None) -> dict:
    """Couverture des besoins d'une marque ce mois-ci : un shift affecté mais en conflit n'est jamais compté comme couvert."""
    inp = inp or build_input(db, p)
    slots = [s for s in inp.slots if code in s.allocations and not s.id.startswith("MANUAL|")]
    shifts = {sh.slot_key: sh for sh in db.scalars(select(m.Shift).where(m.Shift.period_id == p.id))}
    asg = {a.shift_id: a for a in db.scalars(select(m.Assignment).where(m.Assignment.period_id == p.id))}
    names = {e.id: e.name for e in db.scalars(select(m.Employee))}
    site_names = {x.code: x.name for x in db.scalars(select(m.Site))}
    bad: dict = {}
    for v in violations(inp, assignments_for_validation(db, inp, p)):
        for sid in v.slots:
            bad.setdefault(sid, []).append(v.text)
    counts = {"covered": 0, "conflict": 0, "unassigned": 0, "to_place": 0}
    need_min = covered_min = 0
    items = []
    for s in sorted(slots, key=lambda s: (s.day, s.start, s.site, s.id)):
        mins = s.allocations[code]
        need_min += mins
        sh = shifts.get(s.id)
        a = asg.get(sh.id) if sh else None
        state = "to_place" if sh is None else "unassigned" if a is None else "conflict" if s.id in bad else "covered"
        counts[state] += 1
        if state == "covered":
            covered_min += mins
            continue
        items.append({"slot_key": s.id, "state": state, "day": s.day.isoformat(), "start": s.start.isoformat(), "end": s.end.isoformat(), "site": s.site,
                      "site_name": site_names.get(s.site, s.site), "minutes": mins, "shift_id": str(sh.id) if sh else None,
                      "assignment_id": str(a.id) if a else None, "employee": names.get(a.employee_id) if a else None, "conflicts": bad.get(s.id, [])[:3]})
    total = len(slots)
    return {"total": total, **counts, "assigned": counts["covered"] + counts["conflict"], "remaining": total - counts["covered"],
            "need_minutes": need_min, "covered_minutes": covered_min, "remaining_minutes": need_min - covered_min,
            "needs_missing": total == 0, "complete": total > 0 and counts["covered"] == total, "items": items}


def state_of(cov: dict) -> str:
    """needs_missing (besoins à renseigner) | complete (tout attribué, sans conflit) | incomplete."""
    return "needs_missing" if cov["needs_missing"] else "complete" if cov["complete"] else "incomplete"
