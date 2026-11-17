"""Couverture pendant les pauses : sur un site où une présence continue est exigée, la pause d'un collaborateur ne peut être prise que
pendant qu'une autre personne est présente sur le site. L'heure exacte de la pause n'est pas planifiée : on vérifie qu'il existe, pendant
le shift, une période de relève au moins aussi longue que la pause. C'est un signalement (alerte de couverture), pas une contrainte."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Dict, Iterable, List, Set, Tuple

from .model import Assignment, SolverInput
from .timecalc import shift_bounds


def _merge(spans: List[Tuple[datetime, datetime]]) -> List[Tuple[datetime, datetime]]:
    out: List[Tuple[datetime, datetime]] = []
    for a, b in sorted(spans):
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def break_relief_gaps(inp: SolverInput, assignments: Iterable[Assignment], continuous_sites: Set[str]) -> List[Dict]:
    """Shifts avec pause, sur un site à présence continue, pour lesquels aucune relève d'au moins la durée de la pause n'est possible."""
    if not continuous_sites:
        return []
    slots = {s.id: s for s in inp.slots}
    names = {e.id: e.name for e in inp.employees}
    by_site: Dict[tuple, List[tuple]] = defaultdict(list)
    rows = []
    for a in assignments:
        s = slots.get(a.slot_id)
        if s is None or s.site not in continuous_sites:
            continue
        b0, b1 = shift_bounds(s.day, s.start, s.end)
        by_site[s.site].append((a.employee_id, b0, b1))
        rows.append((a, s, b0, b1))
    out: List[Dict] = []
    for a, s, b0, b1 in rows:
        if s.break_minutes <= 0:
            continue
        others = _merge([(max(o0, b0), min(o1, b1)) for eid, o0, o1 in by_site[s.site] if eid != a.employee_id and o0 < b1 and b0 < o1])
        longest = max((int((y - x).total_seconds() // 60) for x, y in others), default=0)
        if longest < s.break_minutes:
            out.append({"slot_id": s.id, "day": s.day.isoformat(), "site": s.site, "start": s.start.strftime("%H:%M"), "end": s.end.strftime("%H:%M"),
                        "employee_id": a.employee_id, "employee": names.get(a.employee_id, a.employee_id), "break_minutes": s.break_minutes,
                        "relief_minutes": longest,
                        "message": (f"{names.get(a.employee_id, a.employee_id)} est seul·e sur {s.site} le {s.day:%d/%m} ({s.start:%H:%M}–{s.end:%H:%M}) : "
                                    f"pause de {s.break_minutes} min sans relève possible"
                                    + (f" (relève la plus longue : {longest} min)." if longest else " (personne d'autre présent)."))})
    return out


__all__ = ["break_relief_gaps"]
