import uuid
from datetime import date, time
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func, select

from .. import models as m
from ..deps import Ctx, audit, get_or_404, require
from ..optimize import enqueue
from ..services_bridge import assignments_for_validation, build_input
from planning_solver.timecalc import shift_hours, split_allocation
from planning_solver.validator import validate
from .crud import serialize

router = APIRouter(tags=["planning"])


class PeriodIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(max_length=100)
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def _c(self):
        if self.end_date < self.start_date or (self.end_date - self.start_date).days > 92:
            raise ValueError("période invalide (max 93 jours)")
        return self


class RunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str = Field("full", pattern="^(full|partial)$")
    time_limit_s: float = Field(30, gt=0, le=600)
    strict_coverage: bool = False
    weights: dict = {}


@router.get("/periods")
def periods(ctx: Ctx = Depends(require("planning.read"))):
    return [serialize(p) for p in ctx.db.scalars(select(m.PlanningPeriod).order_by(m.PlanningPeriod.start_date))]


@router.post("/periods", status_code=201)
def create_period(body: PeriodIn, ctx: Ctx = Depends(require("planning.edit"))):
    p = m.PlanningPeriod(tenant_id=ctx.tenant_id, **body.model_dump())
    ctx.db.add(p)
    ctx.db.flush()
    audit(ctx, "period.create", "period", p.id)
    return serialize(p)


@router.get("/periods/{pid}/schedule")
def schedule(pid: str, ctx: Ctx = Depends(require("planning.read"))):
    p = get_or_404(ctx, m.PlanningPeriod, pid)
    emp = {e.id: e for e in ctx.db.scalars(select(m.Employee))}
    shifts = {s.id: s for s in ctx.db.scalars(select(m.Shift).where(m.Shift.period_id == p.id))}
    allocs: dict = {}
    for b in ctx.db.scalars(select(m.BrandAllocation)):
        allocs.setdefault(b.assignment_id, {})[b.brand_code] = b.minutes
    assigned = set()
    out = []
    for a in ctx.db.scalars(select(m.Assignment).where(m.Assignment.period_id == p.id)):
        s = shifts[a.shift_id]
        assigned.add(s.id)
        out.append({"assignment_id": str(a.id), "shift_id": str(s.id), "slot_key": s.slot_key,
                    "day": s.day.isoformat(), "site": s.site_code, "start": s.start_time.isoformat(),
                    "end": s.end_time.isoformat(), "presence_minutes": s.presence_minutes,
                    "break_minutes": s.break_minutes, "effective_minutes": s.effective_minutes,
                    "employee_id": str(a.employee_id), "employee": emp[a.employee_id].name, "locked": a.locked,
                    "source": a.source, "allocations": allocs.get(a.id, {})})
    out.sort(key=lambda r: (r["day"], r["start"], r["slot_key"]))
    uncovered = [{"shift_id": str(s.id), "slot_key": s.slot_key, "day": s.day.isoformat(), "site": s.site_code,
                  "start": s.start_time.isoformat(), "end": s.end_time.isoformat()}
                 for s in shifts.values() if s.id not in assigned]
    return {"period": serialize(p), "assignments": out, "uncovered": uncovered}


@router.post("/periods/{pid}/runs", status_code=202)
def start_run(pid: str, body: RunIn, ctx: Ctx = Depends(require("planning.optimize")),
              idempotency_key: Optional[str] = Header(None, max_length=100)):
    p = get_or_404(ctx, m.PlanningPeriod, pid)
    if idempotency_key:
        prev = ctx.db.scalar(select(m.OptimizationRun).where(m.OptimizationRun.idempotency_key == idempotency_key))
        if prev is not None:
            return {"run_id": str(prev.id), "status": prev.status, "idempotent_replay": True}
    cfg = {"time_limit_s": body.time_limit_s, "strict_coverage": body.strict_coverage, "weights": body.weights}
    run = m.OptimizationRun(tenant_id=ctx.tenant_id, period_id=p.id, kind=body.kind, config=cfg,
                            idempotency_key=idempotency_key, requested_by=ctx.user.id)
    ctx.db.add(run)
    ctx.db.flush()
    audit(ctx, "optimization.requested", "run", run.id, {"kind": body.kind, "config": cfg})
    rid, tid = str(run.id), str(ctx.tenant_id)
    _after_commit(ctx, lambda: enqueue(tid, rid))
    return {"run_id": rid, "status": "en_attente"}


def _after_commit(ctx: Ctx, fn) -> None:
    from sqlalchemy import event
    event.listen(ctx.db, "after_commit", lambda s: fn(), once=True)


@router.post("/periods/{pid}/reoptimize", status_code=202)
def reoptimize(pid: str, body: RunIn, ctx: Ctx = Depends(require("planning.optimize")),
               idempotency_key: Optional[str] = Header(None, max_length=100)):
    body.kind = "partial"
    return start_run(pid, body, ctx, idempotency_key)


def _run_view(ctx: Ctx, run: m.OptimizationRun) -> dict:
    res = ctx.db.scalar(select(m.OptimizationResult).where(m.OptimizationResult.run_id == run.id))
    return {"id": str(run.id), "period_id": str(run.period_id), "status": run.status, "kind": run.kind,
            "config": run.config, "started_at": run.started_at, "finished_at": run.finished_at,
            "cancel_requested": run.cancel_requested,
            "result_status": res.status if res else None, "mode": res.mode if res else None,
            "duration_s": res.duration_s if res else None}


@router.get("/runs")
def runs(ctx: Ctx = Depends(require("planning.read"))):
    return [_run_view(ctx, r) for r in ctx.db.scalars(select(m.OptimizationRun).order_by(
        m.OptimizationRun.created_at.desc()).limit(50))]


@router.get("/runs/{rid}")
def run(rid: str, ctx: Ctx = Depends(require("planning.read"))):
    return _run_view(ctx, get_or_404(ctx, m.OptimizationRun, rid))


@router.post("/runs/{rid}/cancel", status_code=202)
def cancel(rid: str, ctx: Ctx = Depends(require("planning.optimize"))):
    r = get_or_404(ctx, m.OptimizationRun, rid)
    if r.status in ("termine", "annule", "erreur"):
        raise HTTPException(409, "Exécution déjà terminée")
    r.cancel_requested = True
    audit(ctx, "optimization.cancel", "run", r.id)
    return {"status": "annulation_demandee"}


@router.get("/runs/{rid}/diagnostic")
def diagnostic(rid: str, ctx: Ctx = Depends(require("planning.read"))):
    r = get_or_404(ctx, m.OptimizationRun, rid)
    res = ctx.db.scalar(select(m.OptimizationResult).where(m.OptimizationResult.run_id == r.id))
    if res is None:
        raise HTTPException(409, "Résultat indisponible (exécution en cours ?)")
    return {"run_id": str(r.id), "status": res.status, "mode": res.mode, "duration_s": res.duration_s,
            "report": res.report}


def _set_lock(ctx: Ctx, aid: str, locked: bool) -> dict:
    a = get_or_404(ctx, m.Assignment, aid)
    a.locked = locked
    if locked:
        ctx.db.add(m.LockedAssignment(tenant_id=ctx.tenant_id, assignment_id=a.id, locked_by=ctx.user.id))
    else:
        for l in ctx.db.scalars(select(m.LockedAssignment).where(m.LockedAssignment.assignment_id == a.id)):
            ctx.db.delete(l)
    audit(ctx, "assignment.lock" if locked else "assignment.unlock", "assignment", a.id)
    return {"id": str(a.id), "locked": a.locked}


@router.post("/assignments/{aid}/lock")
def lock(aid: str, ctx: Ctx = Depends(require("planning.edit"))):
    return _set_lock(ctx, aid, True)


@router.post("/assignments/{aid}/unlock")
def unlock(aid: str, ctx: Ctx = Depends(require("planning.edit"))):
    return _set_lock(ctx, aid, False)


class MoveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    employee_id: uuid.UUID


@router.put("/assignments/{aid}")
def reassign(aid: str, body: MoveIn, ctx: Ctx = Depends(require("planning.edit"))):
    """Modification manuelle : enregistrée, et les conflits sont recalculés et renvoyés immédiatement."""
    a = get_or_404(ctx, m.Assignment, aid)
    if a.locked:
        raise HTTPException(409, "Affectation verrouillée : déverrouiller d'abord")
    if ctx.db.get(m.Employee, body.employee_id) is None:
        raise HTTPException(422, "Collaborateur inconnu")
    before = str(a.employee_id)
    a.employee_id, a.source = body.employee_id, "manual"
    ctx.db.flush()
    audit(ctx, "assignment.reassign", "assignment", a.id, {"from": before, "to": str(body.employee_id)})
    return {"id": str(a.id), "conflicts": _conflicts(ctx, a.period_id)}


class ShiftPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start_time: time
    end_time: time
    break_minutes: int = Field(60, ge=0, le=480)


@router.patch("/shifts/{sid}")
def edit_shift(sid: str, body: ShiftPatch, ctx: Ctx = Depends(require("planning.edit"))):
    """Modification d'horaire : durées recalculées côté serveur, imputations proportionnelles, conflits renvoyés."""
    sh = get_or_404(ctx, m.Shift, sid)
    ass = list(ctx.db.scalars(select(m.Assignment).where(m.Assignment.shift_id == sh.id)))
    if any(a.locked for a in ass):
        raise HTTPException(409, "Affectation verrouillée : déverrouiller d'abord")
    try:
        h = shift_hours(sh.day, body.start_time, body.end_time, body.break_minutes)
    except ValueError as e:
        raise HTTPException(422, str(e))
    old = sh.effective_minutes or 1
    sh.start_time, sh.end_time, sh.break_minutes = body.start_time, body.end_time, body.break_minutes
    sh.presence_minutes, sh.effective_minutes = h.presence_minutes, h.effective_minutes
    for a in ass:
        a.source = "manual"
        rows = list(ctx.db.scalars(select(m.BrandAllocation).where(m.BrandAllocation.assignment_id == a.id)))
        parts = split_allocation(h.effective_minutes, {r.brand_code: r.minutes / old for r in rows}) if rows else {}
        for r in rows:
            r.minutes = parts[r.brand_code]
        for b in ctx.db.scalars(select(m.Break).where(m.Break.assignment_id == a.id)):
            b.minutes = body.break_minutes
    ctx.db.flush()
    audit(ctx, "shift.edit", "shift", sh.id, {"start": str(body.start_time), "end": str(body.end_time)})
    return {"id": str(sh.id), "presence_minutes": h.presence_minutes, "effective_minutes": h.effective_minutes,
            "conflicts": _conflicts(ctx, sh.period_id)}


def _conflicts(ctx: Ctx, period_id) -> list:
    p = ctx.db.get(m.PlanningPeriod, period_id)
    inp = build_input(ctx.db, p)
    return validate(inp, assignments_for_validation(ctx.db, inp, p))


@router.get("/periods/{pid}/conflicts")
def conflicts(pid: str, ctx: Ctx = Depends(require("planning.read"))):
    p = get_or_404(ctx, m.PlanningPeriod, pid)
    return {"hard_violations": _conflicts(ctx, p.id)}


# ---- versions ----
def _snapshot(ctx: Ctx, p: m.PlanningPeriod) -> list:
    data = schedule(str(p.id), ctx)
    return [{"slot_key": a["slot_key"], "employee": a["employee"], "day": a["day"], "start": a["start"],
             "end": a["end"], "locked": a["locked"], "allocations": a["allocations"]} for a in data["assignments"]]


@router.post("/periods/{pid}/versions", status_code=201)
def create_version(pid: str, ctx: Ctx = Depends(require("planning.edit")), label: Optional[str] = None):
    p = get_or_404(ctx, m.PlanningPeriod, pid)
    n = (ctx.db.scalar(select(func.max(m.ScheduleVersion.number)).where(m.ScheduleVersion.period_id == p.id))
         or 0) + 1
    last = ctx.db.scalar(select(m.OptimizationResult).order_by(m.OptimizationResult.created_at.desc()).limit(1))
    v = m.ScheduleVersion(tenant_id=ctx.tenant_id, period_id=p.id, number=n, label=label, snapshot=_snapshot(ctx, p),
                          exploratory=(last is None or last.mode != "validable"), created_by=ctx.user.id)
    ctx.db.add(v)
    ctx.db.flush()
    audit(ctx, "version.create", "version", v.id, {"number": n})
    return {"id": str(v.id), "number": n, "exploratory": v.exploratory}


@router.get("/periods/{pid}/versions")
def versions(pid: str, ctx: Ctx = Depends(require("planning.read"))):
    p = get_or_404(ctx, m.PlanningPeriod, pid)
    return [{"id": str(v.id), "number": v.number, "label": v.label, "published": v.published,
             "exploratory": v.exploratory, "created_at": v.created_at, "assignments": len(v.snapshot)}
            for v in ctx.db.scalars(select(m.ScheduleVersion).where(m.ScheduleVersion.period_id == p.id)
                                    .order_by(m.ScheduleVersion.number))]


@router.post("/versions/{vid}/publish")
def publish(vid: str, ctx: Ctx = Depends(require("planning.publish"))):
    v = get_or_404(ctx, m.ScheduleVersion, vid)
    if v.exploratory:
        raise HTTPException(409, "Simulation exploratoire : contrats/besoins incomplets, publication refusée "
                                 "(un planning validable exige des données complètes).")
    if _conflicts(ctx, v.period_id):
        raise HTTPException(409, "Des violations de contraintes dures subsistent")
    v.published = True
    v.published_at = func.now()
    audit(ctx, "version.publish", "version", v.id)
    return {"id": str(v.id), "published": True}


@router.get("/versions/compare")
def compare(a: str, b: str, ctx: Ctx = Depends(require("planning.read"))):
    va, vb = get_or_404(ctx, m.ScheduleVersion, a), get_or_404(ctx, m.ScheduleVersion, b)
    A = {x["slot_key"]: x["employee"] for x in va.snapshot}
    B = {x["slot_key"]: x["employee"] for x in vb.snapshot}
    return {"added": sorted(set(B) - set(A)), "removed": sorted(set(A) - set(B)),
            "changed": [{"slot_key": k, "from": A[k], "to": B[k]} for k in sorted(set(A) & set(B)) if A[k] != B[k]],
            "unchanged": sum(1 for k in set(A) & set(B) if A[k] == B[k])}
