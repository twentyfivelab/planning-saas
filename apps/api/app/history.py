"""Détail d'audit homogène des modifications du planning (qui remplace qui, quand, par qui, sur quel site et quelle marque).
Les noms, horaires, site et marques sont figés au moment de la modification : l'historique reste lisible même si un collaborateur est
renommé ou retiré, ou si un site change de nom."""
from sqlalchemy import select

from . import models as m


def shift_context(db, sh: m.Shift) -> dict:
    brands = sorted(set(db.scalars(select(m.BrandAllocation.brand_code).join(m.Assignment, m.Assignment.id == m.BrandAllocation.assignment_id)
                                   .where(m.Assignment.shift_id == sh.id))))
    site = db.scalar(select(m.Site.name).where(m.Site.code == sh.site_code))
    period = db.get(m.PlanningPeriod, sh.period_id)
    return {"period_id": str(sh.period_id), "period": period.name if period else None, "shift_id": str(sh.id), "slot_key": sh.slot_key,
            "day": sh.day.isoformat(), "site": sh.site_code, "site_name": site or sh.site_code, "brands": brands,
            "start": sh.start_time.isoformat(), "end": sh.end_time.isoformat()}


def assignment_detail(db, sh: m.Shift, from_emp, to_emp, **extra) -> dict:
    emp = lambda e: {"id": str(e.id), "name": e.name} if e is not None else None  # noqa: E731
    ids = [str(e.id) for e in (from_emp, to_emp) if e is not None]
    return {**shift_context(db, sh), "from": emp(from_emp), "to": emp(to_emp), "employee_ids": ids, **extra}
