"""Planning mensuel individuel d'un collaborateur : lecture seule des données du planning existant (aucune copie, aucune période
créée, aucune donnée modifiée en consultant ou en changeant de mois)."""
import calendar as _cal
from collections import defaultdict
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from .. import models as m
from ..deps import Ctx, get_or_404, require
from ..services_bridge import tenant_cap
from .months import MONTHS_FR, parse_month

router = APIRouter(tags=["planning individuel"])


@router.get("/employees/{eid}/month")
def employee_month(eid: str, month: str, ctx: Ctx = Depends(require("planning.read"))):
    e = get_or_404(ctx, m.Employee, eid)
    try:
        first = parse_month(month)
    except Exception:
        raise HTTPException(422, "Mois invalide (AAAA-MM)")
    last = first.replace(day=_cal.monthrange(first.year, first.month)[1])
    period = ctx.db.scalar(select(m.PlanningPeriod).where(m.PlanningPeriod.deleted_at.is_(None), m.PlanningPeriod.start_date <= last, m.PlanningPeriod.end_date >= first)
                           .order_by(m.PlanningPeriod.start_date).limit(1))
    site_names = {s.code: s.name for s in ctx.db.scalars(select(m.Site))}
    rows = ctx.db.execute(select(m.Assignment, m.Shift).join(m.Shift, m.Shift.id == m.Assignment.shift_id)
                          .where(m.Assignment.employee_id == e.id, m.Shift.day >= first, m.Shift.day <= last)
                          .order_by(m.Shift.day, m.Shift.start_time)).all()
    allocs: dict = defaultdict(dict)
    if rows:
        for b in ctx.db.scalars(select(m.BrandAllocation).where(m.BrandAllocation.assignment_id.in_([a.id for a, _s in rows]))):
            allocs[b.assignment_id][b.brand_code] = b.minutes
    by_day: dict = defaultdict(list)
    for a, sh in rows:
        by_day[sh.day].append({"assignment_id": str(a.id), "shift_id": str(sh.id), "period_id": str(a.period_id), "start": sh.start_time.isoformat()[:5],
                               "end": sh.end_time.isoformat()[:5], "break_minutes": sh.break_minutes, "presence_minutes": sh.presence_minutes,
                               "effective_minutes": sh.effective_minutes, "site": sh.site_code, "site_name": site_names.get(sh.site_code, sh.site_code),
                               "brands": sorted(allocs.get(a.id, {})), "allocations": allocs.get(a.id, {}), "locked": a.locked, "source": a.source})
    unav = list(ctx.db.scalars(select(m.Unavailability).where(m.Unavailability.employee_id == e.id)))
    dated = {u.on_date: u.reason for u in unav if u.on_date and first <= u.on_date <= last}
    weekly = {u.weekday for u in unav if u.weekday is not None}
    avail = {a.weekday for a in ctx.db.scalars(select(m.Availability).where(m.Availability.employee_id == e.id))}
    partial: dict = defaultdict(list)  # absences sur une partie de la journée : le reste du jour reste travaillable
    for pa in ctx.db.scalars(select(m.PartialAbsence).where(m.PartialAbsence.employee_id == e.id, m.PartialAbsence.on_date >= first,
                                                          m.PartialAbsence.on_date <= last).order_by(m.PartialAbsence.start_time)):
        partial[pa.on_date].append({"start": pa.start_time.isoformat()[:5], "end": pa.end_time.isoformat()[:5], "reason": pa.reason})
    leaves = {}
    for lv in ctx.db.scalars(select(m.LeaveRequest).where(m.LeaveRequest.employee_id == e.id, m.LeaveRequest.status == "approved",
                                                          m.LeaveRequest.start_date <= last, m.LeaveRequest.end_date >= first)):
        d = max(lv.start_date, first)
        while d <= min(lv.end_date, last):
            leaves[d] = lv.kind
            d += timedelta(days=1)
    days = []
    d = first
    while d <= last:
        items = by_day.get(d, [])
        if d in leaves:
            off = {"kind": "conge", "label": "Congé" if leaves[d] == "leave" else f"Congé ({leaves[d]})"}
        elif d in dated:
            off = {"kind": "indisponible", "label": "Indisponible" + (f" ({dated[d]})" if dated[d] and dated[d] not in ("calendrier", "absence") else "")}
        elif d.weekday() in weekly or (avail and d.weekday() not in avail):
            off = {"kind": "indisponible_recurrent", "label": "Indisponible (chaque semaine)"}
        else:
            off = None
        days.append({"date": d.isoformat(), "weekday": d.weekday(), "assignments": items, "off": off, "partial": partial.get(d, [])})
        d += timedelta(days=1)
    worked = [x for x in days if x["assignments"]]
    eff = sum(a["effective_minutes"] for x in worked for a in x["assignments"])
    return {
        "employee": {"id": str(e.id), "name": e.name, "deleted": e.deleted_at is not None},
        "month": first.strftime("%Y-%m"), "label": f"{MONTHS_FR[first.month - 1]} {first.year}",
        "period": {"id": str(period.id), "name": period.name, "archived": period.archived_at is not None} if period else None,
        "has_plan": bool(period) and ctx.db.scalar(select(m.Assignment.id).where(m.Assignment.period_id == period.id).limit(1)) is not None,
        "days": days,
        "totals": {"effective_minutes": eff, "days_worked": len(worked), "sundays_worked": sum(1 for x in worked if x["weekday"] == 6),
                   "presence_minutes": sum(a["presence_minutes"] for x in worked for a in x["assignments"]),
                   "break_minutes": sum(a["break_minutes"] for x in worked for a in x["assignments"])},
        "limits": {"monthly_cap_minutes": tenant_cap(ctx.db, ctx.tenant_id), "min_days_month": e.min_days_month, "max_days_month": e.max_days_month},
    }
