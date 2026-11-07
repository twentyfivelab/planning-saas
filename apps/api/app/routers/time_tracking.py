"""Heures réellement effectuées : saisie distincte du planning. Le prévu est recopié à la saisie ; le planning initial n'est jamais modifié."""
import uuid
from collections import defaultdict
from datetime import date, datetime, time, timezone
from typing import Dict, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select

from planning_solver.timecalc import shift_hours

from .. import models as m
from ..deps import Ctx, audit, get_or_404, require
from .planning import scope_brands

router = APIRouter(tags=["heures réelles"])


def _minutes_between(a: time, b: time) -> int:
    return (b.hour * 60 + b.minute) - (a.hour * 60 + a.minute)


def _entry_view(t: m.TimeEntry, names: dict) -> dict:
    return {"id": str(t.id), "status": t.status, "actual_start": t.actual_start.isoformat()[:5] if t.actual_start else None, "actual_end": t.actual_end.isoformat()[:5] if t.actual_end else None,
            "actual_break_minutes": t.actual_break_minutes, "worked_minutes": t.worked_minutes, "late_minutes": t.late_minutes, "overtime_minutes": t.overtime_minutes,
            "absence_reason": t.absence_reason, "note": t.note, "validated": t.validated_at is not None, "validated_by": names.get(t.validated_by), "validated_at": t.validated_at.isoformat() if t.validated_at else None}


@router.get("/periods/{pid}/time-entries")
def time_entries(pid: str, day: Optional[date] = None, employee_id: Optional[uuid.UUID] = None, ctx: Ctx = Depends(require("planning.brand"))):
    """Pour chaque shift affecté : le prévu (planning) et le réel saisi. Un responsable de marque ne voit que ses marques."""
    p = get_or_404(ctx, m.PlanningPeriod, pid)
    scope = scope_brands(ctx)
    emps = {e.id: e.name for e in ctx.db.scalars(select(m.Employee))}
    names = {u.id: u.name for u in ctx.db.scalars(select(m.User))}
    shifts = {s.id: s for s in ctx.db.scalars(select(m.Shift).where(m.Shift.period_id == p.id))}
    entries = {(t.shift_id, t.employee_id): t for t in ctx.db.scalars(select(m.TimeEntry).where(m.TimeEntry.period_id == p.id))}
    rows = list(ctx.db.scalars(select(m.Assignment).where(m.Assignment.period_id == p.id)))
    allocs: Dict = defaultdict(dict)
    if rows:
        for r in ctx.db.scalars(select(m.BrandAllocation).where(m.BrandAllocation.assignment_id.in_([a.id for a in rows]))):
            allocs[r.assignment_id][r.brand_code] = r.minutes
    out = []
    for a in rows:
        s = shifts[a.shift_id]
        if (day and s.day != day) or (employee_id and a.employee_id != employee_id) or (scope is not None and not (scope & set(allocs[a.id]))):
            continue
        t = entries.get((s.id, a.employee_id))
        out.append({"shift_id": str(s.id), "employee_id": str(a.employee_id), "employee": emps.get(a.employee_id), "day": s.day.isoformat(), "site": s.site_code, "brands": sorted(allocs[a.id]),
                    "planned_start": s.start_time.isoformat()[:5], "planned_end": s.end_time.isoformat()[:5], "planned_break_minutes": s.break_minutes, "planned_minutes": s.effective_minutes,
                    "entry": _entry_view(t, names) if t else None})
    out.sort(key=lambda r: (r["day"], r["planned_start"], r["employee"] or ""))
    return {"rows": out, "summary": _summary(ctx, p, entries, rows, shifts, emps, scope, allocs)}


def _summary(ctx: Ctx, p: m.PlanningPeriod, entries: dict, rows: list, shifts: dict, emps: dict, scope, allocs: dict) -> dict:
    by: Dict[uuid.UUID, dict] = {}
    today = date.today()
    for a in rows:
        s = shifts[a.shift_id]
        if scope is not None and not (scope & set(allocs[a.id])):
            continue
        r = by.setdefault(a.employee_id, {"employee_id": str(a.employee_id), "employee": emps.get(a.employee_id), "planned_minutes": 0, "worked_minutes": 0, "validated_minutes": 0, "overtime_minutes": 0,
                                          "late_minutes": 0, "absences": 0, "missing_entries": 0})
        r["planned_minutes"] += s.effective_minutes
        t = entries.get((s.id, a.employee_id))
        if t is None:
            if s.day < today:
                r["missing_entries"] += 1
            continue
        r["worked_minutes"] += t.worked_minutes
        r["overtime_minutes"] += t.overtime_minutes
        r["late_minutes"] += t.late_minutes
        r["absences"] += 1 if t.status == "absent" else 0
        if t.validated_at is not None:
            r["validated_minutes"] += t.worked_minutes
    return {"employees": sorted(by.values(), key=lambda r: r["employee"] or ""), "to_validate": sum(1 for t in entries.values() if t.validated_at is None)}


class TimeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["worked", "absent"] = "worked"
    actual_start: Optional[time] = None
    actual_end: Optional[time] = None
    actual_break_minutes: Optional[int] = Field(None, ge=0, le=480)
    absence_reason: Optional[str] = Field(None, max_length=200)
    note: Optional[str] = Field(None, max_length=300)

    @model_validator(mode="after")
    def _t(self):
        if self.status == "worked" and (self.actual_start is None or self.actual_end is None):
            raise ValueError("Indiquez l'heure réelle d'arrivée et de départ.")
        return self


@router.put("/shifts/{sid}/time-entry")
def save_entry(sid: str, body: TimeIn, ctx: Ctx = Depends(require("time.write"))):
    """Enregistre le réel d'un shift. Modifier une saisie validée en retire la validation (tracé) : le responsable devra revalider."""
    s = get_or_404(ctx, m.Shift, sid)
    a = ctx.db.scalar(select(m.Assignment).where(m.Assignment.shift_id == s.id))
    if a is None:
        raise HTTPException(409, "Ce shift n'a pas de titulaire : aucune heure ne peut y être saisie.")
    if body.status == "worked" and s.day > date.today():
        raise HTTPException(422, "Ce shift n'a pas encore eu lieu : seule une absence peut être enregistrée à l'avance.")
    worked = late = 0
    if body.status == "worked":
        brk = s.break_minutes if body.actual_break_minutes is None else body.actual_break_minutes
        try:
            h = shift_hours(s.day, body.actual_start, body.actual_end, brk)
        except ValueError as e:
            raise HTTPException(422, str(e))
        worked = h.effective_minutes
        late = max(0, _minutes_between(s.start_time, body.actual_start))
    t = ctx.db.scalar(select(m.TimeEntry).where(m.TimeEntry.shift_id == s.id, m.TimeEntry.employee_id == a.employee_id))
    planned = s.effective_minutes
    created = t is None
    if t is None:
        allocations = {r.brand_code: r.minutes for r in ctx.db.scalars(select(m.BrandAllocation).where(m.BrandAllocation.assignment_id == a.id))}
        t = m.TimeEntry(tenant_id=ctx.tenant_id, shift_id=s.id, period_id=s.period_id, employee_id=a.employee_id, day=s.day, site_code=s.site_code, allocations=allocations,
                        planned_start=s.start_time, planned_end=s.end_time, planned_break_minutes=s.break_minutes, planned_minutes=planned)
        ctx.db.add(t)
    was_validated = t.validated_at is not None
    t.status, t.actual_start, t.actual_end = body.status, body.actual_start if body.status == "worked" else None, body.actual_end if body.status == "worked" else None
    t.actual_break_minutes = (s.break_minutes if body.actual_break_minutes is None else body.actual_break_minutes) if body.status == "worked" else None
    t.worked_minutes, t.late_minutes, t.overtime_minutes = worked, late, max(0, worked - t.planned_minutes)
    t.absence_reason, t.note, t.entered_by = body.absence_reason if body.status == "absent" else None, body.note, ctx.user.id
    t.validated_by, t.validated_at = None, None
    ctx.db.flush()
    audit(ctx, "time.save", "time_entry", t.id, {"shift_id": str(s.id), "day": s.day.isoformat(), "employee_id": str(a.employee_id), "status": body.status, "worked_minutes": worked,
                                                 "created": created, "validation_removed": was_validated})
    return _entry_view(t, {})


@router.delete("/shifts/{sid}/time-entry", status_code=204)
def delete_entry(sid: str, ctx: Ctx = Depends(require("time.write"))):
    """Retire une saisie erronée. Une saisie validée doit d'abord perdre sa validation : les heures validées ne disparaissent jamais par accident."""
    s = get_or_404(ctx, m.Shift, sid)
    rows = list(ctx.db.scalars(select(m.TimeEntry).where(m.TimeEntry.shift_id == s.id)))
    if not rows:
        raise HTTPException(404, "Aucune saisie sur ce shift.")
    if any(t.validated_at is not None for t in rows):
        raise HTTPException(409, "Ces heures sont validées : retirez d'abord la validation.")
    for t in rows:
        audit(ctx, "time.delete", "time_entry", t.id, {"shift_id": str(s.id), "day": t.day.isoformat(), "employee_id": str(t.employee_id), "worked_minutes": t.worked_minutes})
        ctx.db.delete(t)


def _validate_rights(ctx: Ctx, t: m.TimeEntry) -> None:
    if ctx.user.employee_id is not None and ctx.user.employee_id == t.employee_id:
        raise HTTPException(403, "Vous ne pouvez pas valider vos propres heures : un autre responsable doit le faire.")
    scope = scope_brands(ctx)
    if scope is not None and not (scope & set(t.allocations or {})):
        raise HTTPException(403, "Ces heures concernent une marque hors de votre périmètre.")


@router.post("/time-entries/{tid}/validate")
def validate_entry(tid: str, ctx: Ctx = Depends(require("time.validate"))):
    t = get_or_404(ctx, m.TimeEntry, tid)
    _validate_rights(ctx, t)
    t.validated_by, t.validated_at = ctx.user.id, datetime.now(timezone.utc)
    ctx.db.flush()
    audit(ctx, "time.validate", "time_entry", t.id, {"day": t.day.isoformat(), "employee_id": str(t.employee_id), "worked_minutes": t.worked_minutes})
    return _entry_view(t, {ctx.user.id: ctx.user.name})


@router.post("/time-entries/{tid}/unvalidate")
def unvalidate_entry(tid: str, ctx: Ctx = Depends(require("time.validate"))):
    t = get_or_404(ctx, m.TimeEntry, tid)
    _validate_rights(ctx, t)
    t.validated_by, t.validated_at = None, None
    ctx.db.flush()
    audit(ctx, "time.unvalidate", "time_entry", t.id, {"day": t.day.isoformat(), "employee_id": str(t.employee_id)})
    return _entry_view(t, {})
