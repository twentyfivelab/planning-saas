"""Absence touchant un planning officiel (version validée ou publiée) : alerte et proposition de révision.
Rien n'est modifié automatiquement : les gestionnaires sont notifiés une fois par absence, avec les shifts concernés ; ils choisissent
ensuite des remplaçants (classement expliqué) ou une réoptimisation locale, puis créent, valident et publient une nouvelle version."""
from datetime import date
from typing import Iterable, List

from sqlalchemy import select

from . import models as m
from .period_state import has_official_version
from .rbac import has_permission

DAYS = ("lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim.")


def propose_revision(db, tenant_id, employee: m.Employee, dates: Iterable[date], actor_id=None) -> List[dict]:
    dates = sorted(set(dates))
    if not dates:
        return []
    rows = db.execute(select(m.Assignment, m.Shift, m.PlanningPeriod).join(m.Shift, m.Shift.id == m.Assignment.shift_id)
                      .join(m.PlanningPeriod, m.PlanningPeriod.id == m.Assignment.period_id)
                      .where(m.Assignment.employee_id == employee.id, m.Shift.day.in_(dates))).all()
    by_period: dict = {}
    for a, sh, p in rows:
        by_period.setdefault(p, []).append((a, sh))
    out = []
    managers = [u for u in db.scalars(select(m.User).where(m.User.is_active.is_(True))) if has_permission(u.role, "planning.edit")]
    for p, items in by_period.items():
        if p.archived_at is not None or not has_official_version(db, p.id):
            continue
        shifts = [{"assignment_id": str(a.id), "shift_id": str(sh.id), "day": sh.day.isoformat(), "start": sh.start_time.isoformat()[:5],
                   "end": sh.end_time.isoformat()[:5], "site": sh.site_code} for a, sh in sorted(items, key=lambda x: (x[1].day, x[1].start_time))]
        text = ", ".join(f"{DAYS[date.fromisoformat(s['day']).weekday()]} {s['day'][8:10]}/{s['day'][5:7]} {s['start']}–{s['end']} {s['site']}" for s in shifts[:6])
        title = f"Révision proposée : {p.name}"
        body = (f"Absence de {employee.name} : {len(shifts)} shift(s) du planning validé ou publié sont concernés ({text}"
                f"{' …' if len(shifts) > 6 else ''}). Ouvrez le planning pour choisir des remplaçants, puis publiez une nouvelle version.")
        payload = {"period_id": str(p.id), "employee_id": str(employee.id), "dates": [d.isoformat() for d in dates], "shifts": shifts}
        for u in managers:
            dup = db.scalar(select(m.Notification.id).where(m.Notification.user_id == u.id, m.Notification.kind == "revision_needed",
                                                            m.Notification.read_at.is_(None), m.Notification.payload["period_id"].astext == str(p.id),
                                                            m.Notification.payload["employee_id"].astext == str(employee.id),
                                                            m.Notification.payload["dates"] == payload["dates"]).limit(1))
            if dup is None:
                db.add(m.Notification(tenant_id=tenant_id, user_id=u.id, kind="revision_needed", title=title, body=body, payload=payload))
        db.add(m.AuditLog(tenant_id=tenant_id, user_id=actor_id, action="period.revision_proposed", entity="period", entity_id=str(p.id),
                          detail={"employee": employee.name, "shifts": len(shifts), "dates": payload["dates"]}))
        out.append({"period_id": str(p.id), "period": p.name, "shifts": shifts})
    db.flush()
    return out
