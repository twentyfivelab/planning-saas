"""Rappels « À régulariser » : un remplacement confirmé malgré une affectation existante le même jour est enregistré
provisoirement ; le rappel reste visible tant que la double affectation existe et disparaît dès que l'affectation initiale est
retirée ou réattribuée (ou que la nouvelle n'existe plus). Rien n'est supprimé ni réattribué automatiquement."""
from datetime import datetime, timezone
from typing import List

from sqlalchemy import select

from . import models as m


def register_doubles(db, tenant_id, period_id, employee_id, new_assignment_id, user_id=None) -> int:
    """Crée un rappel par affectation initiale du même collaborateur le même jour (sans doublon de rappel ouvert)."""
    new = db.get(m.Assignment, new_assignment_id)
    if new is None:
        return 0
    sh = db.get(m.Shift, new.shift_id)
    others = db.execute(select(m.Assignment).join(m.Shift, m.Shift.id == m.Assignment.shift_id)
                        .where(m.Assignment.employee_id == employee_id, m.Shift.day == sh.day, m.Assignment.id != new.id)).scalars().all()
    n = 0
    for o in others:
        exists = db.scalar(select(m.Regularization.id).where(m.Regularization.resolved_at.is_(None), m.Regularization.employee_id == employee_id,
                                                             ((m.Regularization.new_assignment_id == new.id) & (m.Regularization.initial_assignment_id == o.id))
                                                             | ((m.Regularization.new_assignment_id == o.id) & (m.Regularization.initial_assignment_id == new.id))).limit(1))
        if exists is None:
            db.add(m.Regularization(tenant_id=tenant_id, period_id=period_id, employee_id=employee_id, day=sh.day, new_assignment_id=new.id,
                                    initial_assignment_id=o.id, created_by=user_id))
            n += 1
    db.flush()
    return n


def _still_double(db, r: m.Regularization) -> bool:
    a, b = db.get(m.Assignment, r.new_assignment_id), db.get(m.Assignment, r.initial_assignment_id)
    return a is not None and b is not None and a.employee_id == r.employee_id and b.employee_id == r.employee_id


def resolve(db, period_id=None) -> int:
    """Clôt les rappels dont la double affectation n'existe plus (appelé après chaque enregistrement réussi)."""
    q = select(m.Regularization).where(m.Regularization.resolved_at.is_(None))
    if period_id is not None:
        q = q.where(m.Regularization.period_id == period_id)
    n = 0
    for r in db.scalars(q):
        if not _still_double(db, r):
            init = db.get(m.Assignment, r.initial_assignment_id)
            r.resolved_at = datetime.now(timezone.utc)
            r.resolution = ("affectation initiale retirée" if init is None else "affectation initiale réattribuée" if init.employee_id != r.employee_id
                            else "nouvelle affectation retirée ou réattribuée")
            n += 1
    if n:
        db.flush()
    return n


def open_items(db, period_id) -> List[dict]:
    """Rappels ouverts et TOUJOURS valides (contrôle à la lecture : jamais un rappel obsolète affiché)."""
    site_names = {s.code: s.name for s in db.scalars(select(m.Site))}
    out = []
    for r in db.scalars(select(m.Regularization).where(m.Regularization.period_id == period_id, m.Regularization.resolved_at.is_(None))
                        .order_by(m.Regularization.day, m.Regularization.created_at)):
        if not _still_double(db, r):
            continue
        e = db.get(m.Employee, r.employee_id)

        def desc(aid):
            a = db.get(m.Assignment, aid)
            sh = db.get(m.Shift, a.shift_id)
            brands = sorted(x.brand_code for x in db.scalars(select(m.BrandAllocation).where(m.BrandAllocation.assignment_id == a.id)))
            return {"assignment_id": str(a.id), "shift_id": str(sh.id), "site": sh.site_code, "site_name": site_names.get(sh.site_code, sh.site_code),
                    "brands": brands, "start": sh.start_time.isoformat()[:5], "end": sh.end_time.isoformat()[:5], "locked": a.locked}
        out.append({"id": str(r.id), "employee_id": str(r.employee_id), "employee": e.name if e else "—", "day": r.day.isoformat(),
                    "new": desc(r.new_assignment_id), "initial": desc(r.initial_assignment_id), "created_at": r.created_at.isoformat()})
    return out
