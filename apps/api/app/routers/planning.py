import uuid
from datetime import date, time
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select

from .. import models as m
from ..deps import Ctx, audit, get_or_404, require
from .. import regularize
from ..limits import guard_monthly_cap, month_minutes
from ..optimize import enqueue
from ..period_state import ensure_editable, has_official_version, statuses
from ..services_bridge import assignments_for_validation, build_input
from planning_solver.sundays import sunday_summary
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
    confirm_replace: bool = False  # un planning validé ou publié n'est jamais remplacé sans confirmation explicite
    # paramètres d'un planning qui en conserve déjà : « frozen » (par défaut) = ceux du planning ; « current » = paramètres actuels (choix explicite)
    params: Optional[Literal["frozen", "current"]] = None


def scope_brands(ctx: Ctx) -> Optional[set]:
    """Périmètre d'un responsable de marque (ses marques uniquement) ; None = tout le tenant."""
    return set((ctx.user.scope or {}).get("brands") or []) if ctx.user.role == "brand_manager" else None


@router.get("/periods")
def periods(ctx: Ctx = Depends(require("self.read"))):  # mois et statuts seulement : aucune donnée de collaborateur
    rows = list(ctx.db.scalars(select(m.PlanningPeriod).where(m.PlanningPeriod.deleted_at.is_(None)).order_by(m.PlanningPeriod.start_date)))
    st = statuses(ctx.db, rows)
    return [{**serialize(p), **st[p.id]} for p in rows]


@router.post("/periods", status_code=201)
def create_period(body: PeriodIn, ctx: Ctx = Depends(require("planning.edit"))):
    p = m.PlanningPeriod(tenant_id=ctx.tenant_id, **body.model_dump())
    ctx.db.add(p)
    ctx.db.flush()
    audit(ctx, "period.create", "period", p.id)
    return serialize(p)


@router.get("/periods/{pid}/schedule")
def schedule(pid: str, ctx: Ctx = Depends(require("planning.brand"))):
    p = get_or_404(ctx, m.PlanningPeriod, pid)
    scope = scope_brands(ctx)
    emp = {e.id: e for e in ctx.db.scalars(select(m.Employee))}
    site_names = {x.code: x.name for x in ctx.db.scalars(select(m.Site))}  # nom actuel ; le code (stable) reste la référence
    shifts = {s.id: s for s in ctx.db.scalars(select(m.Shift).where(m.Shift.period_id == p.id))}
    allocs: dict = {}
    for b in ctx.db.scalars(select(m.BrandAllocation)):
        allocs.setdefault(b.assignment_id, {})[b.brand_code] = b.minutes
    assigned = set()
    out = []
    for a in ctx.db.scalars(select(m.Assignment).where(m.Assignment.period_id == p.id)):
        s = shifts[a.shift_id]
        assigned.add(s.id)
        if scope is not None and not (scope & set(allocs.get(a.id, {}))):
            continue
        out.append({"assignment_id": str(a.id), "shift_id": str(s.id), "slot_key": s.slot_key,
                    "day": s.day.isoformat(), "site": s.site_code, "site_name": site_names.get(s.site_code, s.site_code), "start": s.start_time.isoformat(),
                    "end": s.end_time.isoformat(), "presence_minutes": s.presence_minutes,
                    "break_minutes": s.break_minutes, "effective_minutes": s.effective_minutes,
                    "employee_id": str(a.employee_id), "employee": emp[a.employee_id].name, "locked": a.locked,
                    "source": a.source, "allocations": allocs.get(a.id, {})})
    out.sort(key=lambda r: (r["day"], r["start"], r["slot_key"]))
    uncovered = [{"shift_id": str(s.id), "slot_key": s.slot_key, "day": s.day.isoformat(), "site": s.site_code, "site_name": site_names.get(s.site_code, s.site_code),
                  "start": s.start_time.isoformat(), "end": s.end_time.isoformat()}
                 for s in shifts.values() if s.id not in assigned]
    if scope is not None:
        uncovered = []  # un shift non couvert n'a pas encore d'imputation : il n'est pas attribuable à une marque du périmètre
    return {"period": serialize(p), "assignments": out, "uncovered": uncovered}


@router.post("/periods/{pid}/runs", status_code=202)
def start_run(pid: str, body: RunIn, ctx: Ctx = Depends(require("planning.optimize")),
              idempotency_key: Optional[str] = Header(None, max_length=100)):
    p = get_or_404(ctx, m.PlanningPeriod, pid)
    ensure_editable(ctx.db, p.id)
    if idempotency_key:
        prev = ctx.db.scalar(select(m.OptimizationRun).where(m.OptimizationRun.idempotency_key == idempotency_key))
        if prev is not None:
            return {"run_id": str(prev.id), "status": prev.status, "idempotent_replay": True}
    if has_official_version(ctx.db, p.id) and not body.confirm_replace:
        raise HTTPException(409, detail={"code": "official_version", "message": f"{p.name} a une version validée ou publiée : elle reste conservée, mais le planning en cours serait remplacé. Confirmez pour continuer, ou utilisez une simulation."})
    cfg = {"time_limit_s": body.time_limit_s, "strict_coverage": body.strict_coverage, "weights": body.weights}
    if body.params:
        cfg["params"] = body.params
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
            "cancel_requested": run.cancel_requested, "simulation": run.simulation, "applied_at": run.applied_at,
            "result_status": res.status if res else None, "mode": res.mode if res else None,
            "duration_s": res.duration_s if res else None, "progress": run.progress,
            # résultat d'enregistrement (planning remplacé ou conservé, et pourquoi) et temps mesurés de chaque étape
            "save": (res.report or {}).get("save") if res else None, "timing": (res.report or {}).get("timing") if res else None}


@router.get("/runs")
def runs(ctx: Ctx = Depends(require("planning.read"))):
    gone = select(m.PlanningPeriod.id).where(m.PlanningPeriod.deleted_at.is_not(None))
    return [_run_view(ctx, r) for r in ctx.db.scalars(select(m.OptimizationRun).where(m.OptimizationRun.simulation.is_(False), m.OptimizationRun.period_id.not_in(gone)).order_by(
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
    ensure_editable(ctx.db, a.period_id)
    a.locked = locked
    if locked:
        ctx.db.add(m.LockedAssignment(tenant_id=ctx.tenant_id, assignment_id=a.id, locked_by=ctx.user.id))
    else:
        for l in ctx.db.scalars(select(m.LockedAssignment).where(m.LockedAssignment.assignment_id == a.id)):
            ctx.db.delete(l)
    from ..history import assignment_detail
    who = ctx.db.get(m.Employee, a.employee_id)
    audit(ctx, "assignment.lock" if locked else "assignment.unlock", "assignment", a.id, assignment_detail(ctx.db, ctx.db.get(m.Shift, a.shift_id), who, who))
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
    ensure_editable(ctx.db, a.period_id)
    if a.locked:
        raise HTTPException(409, "Affectation verrouillée : déverrouiller d'abord")
    if ctx.db.get(m.Employee, body.employee_id) is None:
        raise HTTPException(422, "Collaborateur inconnu")
    new = ctx.db.get(m.Employee, body.employee_id)
    sh0 = ctx.db.get(m.Shift, a.shift_id)
    if new.deleted_at is not None:
        raise HTTPException(422, f"{new.name} a été supprimé·e de l'équipe : plus aucun shift ne peut lui être attribué (réintégrez-le d'abord).")
    month = [(sh0.day.year, sh0.day.month)]
    before_minutes = month_minutes(ctx.db, [new.id, a.employee_id], month)
    brands = {r.brand_code for r in ctx.db.scalars(select(m.BrandAllocation).where(m.BrandAllocation.assignment_id == a.id))}
    missing = sorted(b for b in brands if b not in (new.brands or {}))
    if missing:  # une marque non sélectionnée dans la fiche n'est jamais attribuée
        raise HTTPException(422, f"{', '.join(missing)} n'est pas autorisée pour {new.name} (fiche collaborateur).")
    old = ctx.db.get(m.Employee, a.employee_id)
    a.employee_id, a.source = body.employee_id, "manual"
    ctx.db.flush()
    guard_monthly_cap(ctx.db, ctx.tenant_id, before_minutes, [new.id], month)
    regularize.resolve(ctx.db, a.period_id)
    regularize.register_doubles(ctx.db, ctx.tenant_id, a.period_id, new.id, a.id, ctx.user.id)  # double affectation : rappel
    from ..history import assignment_detail
    audit(ctx, "assignment.reassign", "assignment", a.id, assignment_detail(ctx.db, ctx.db.get(m.Shift, a.shift_id), old, new))
    return {"id": str(a.id), "conflicts": _conflicts(ctx, a.period_id)}


def _allowed_schedules(ctx: Ctx, sh: m.Shift) -> list:
    """Horaires autorisés pour la boutique et les marques d'un shift (modèles de shifts à portée). Vide = non restreint."""
    brands = {r.brand_code for r in ctx.db.scalars(
        select(m.BrandAllocation).join(m.Assignment, m.Assignment.id == m.BrandAllocation.assignment_id)
        .where(m.Assignment.shift_id == sh.id))}
    groups = {b.group_code for b in ctx.db.scalars(select(m.Brand).where(m.Brand.code.in_(brands))) if b.group_code} if brands else set()
    keys = {sh.site_code} | brands | groups | {f"{b}@{sh.site_code}" for b in brands}
    out = []
    for t in ctx.db.scalars(select(m.ShiftTemplate).where(m.ShiftTemplate.scope_code.in_(keys)).order_by(m.ShiftTemplate.start_time)):
        out.append({"template": t.code, "start": t.start_time.isoformat(), "end": t.end_time.isoformat(),
                    "break_minutes": t.break_minutes, "scope": t.scope_code})
    seen, uniq = set(), []
    for o in out:
        if (o["start"], o["end"]) not in seen:
            seen.add((o["start"], o["end"]))
            uniq.append(o)
    return uniq


@router.get("/shifts/{sid}/allowed-times")
def allowed_times(sid: str, ctx: Ctx = Depends(require("planning.read"))):
    sh = get_or_404(ctx, m.Shift, sid)
    return {"site": sh.site_code, "allowed": _allowed_schedules(ctx, sh),
            "can_override": ctx.user.role in ("owner", "admin")}


@router.get("/periods/{pid}/sunday-summary")
def sunday(pid: str, ctx: Ctx = Depends(require("planning.read"))):
    """Compteur des dimanches calculé sur les vrais shifts et les vrais quotas (jamais une valeur statique)."""
    p = get_or_404(ctx, m.PlanningPeriod, pid)
    inp = build_input(ctx.db, p)
    return sunday_summary(inp, assignments_for_validation(ctx.db, inp, p))


class ShiftPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start_time: time
    end_time: time
    break_minutes: int = Field(60, ge=0, le=480)


@router.patch("/shifts/{sid}")
def edit_shift(sid: str, body: ShiftPatch, ctx: Ctx = Depends(require("planning.edit"))):
    """Modification d'horaire : durées recalculées côté serveur, imputations proportionnelles, conflits renvoyés."""
    sh = get_or_404(ctx, m.Shift, sid)
    ensure_editable(ctx.db, sh.period_id)
    allowed = _allowed_schedules(ctx, sh)
    if allowed and not any(a["start"] == body.start_time.isoformat() and a["end"] == body.end_time.isoformat() for a in allowed):
        if ctx.user.role not in ("owner", "admin"):
            ok = ", ".join(f"{a['start'][:5]}–{a['end'][:5]}" for a in allowed)
            raise HTTPException(422, f"Horaire non autorisé pour {sh.site_code}. Horaires autorisés : {ok}. Seul un administrateur peut déroger.")
        from ..approval import override_refusal
        mine = override_refusal(ctx, [a.employee_id for a in ctx.db.scalars(select(m.Assignment).where(m.Assignment.shift_id == sh.id))])
        if mine:
            raise HTTPException(403, mine)  # personne n'approuve une dérogation qui la concerne
        audit(ctx, "shift.schedule_override", "shift", sh.id, {"start": str(body.start_time), "end": str(body.end_time)})
    ass = list(ctx.db.scalars(select(m.Assignment).where(m.Assignment.shift_id == sh.id)))
    if any(a.locked for a in ass):
        raise HTTPException(409, "Affectation verrouillée : déverrouiller d'abord")
    try:
        h = shift_hours(sh.day, body.start_time, body.end_time, body.break_minutes)
    except ValueError as e:
        raise HTTPException(422, str(e))
    old = sh.effective_minutes or 1
    from ..history import shift_context
    before_ctx = {**shift_context(ctx.db, sh), "break_minutes": sh.break_minutes}  # valeurs AVANT la modification (historique)
    month = [(sh.day.year, sh.day.month)]
    before_minutes = month_minutes(ctx.db, [a.employee_id for a in ass], month)
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
    guard_monthly_cap(ctx.db, ctx.tenant_id, before_minutes, [a.employee_id for a in ass], month)
    who = [ctx.db.get(m.Employee, a.employee_id) for a in ass]
    audit(ctx, "shift.edit", "shift", sh.id, {**before_ctx, "start": str(body.start_time), "end": str(body.end_time),
                                               "before": {"start": before_ctx["start"], "end": before_ctx["end"], "break_minutes": before_ctx["break_minutes"]},
                                               "after": {"start": body.start_time.isoformat(), "end": body.end_time.isoformat(), "break_minutes": body.break_minutes},
                                               "employees": [{"id": str(e.id), "name": e.name} for e in who if e], "employee_ids": [str(e.id) for e in who if e],
                                               "override": bool(allowed) and not any(a_["start"] == body.start_time.isoformat() and a_["end"] == body.end_time.isoformat() for a_ in allowed)})
    return {"id": str(sh.id), "presence_minutes": h.presence_minutes, "effective_minutes": h.effective_minutes,
            "conflicts": _conflicts(ctx, sh.period_id)}


def _conflicts(ctx: Ctx, period_id) -> list:
    p = ctx.db.get(m.PlanningPeriod, period_id)
    inp = build_input(ctx.db, p)
    return validate(inp, assignments_for_validation(ctx.db, inp, p))


@router.get("/periods/{pid}/break-coverage")
def break_coverage(pid: str, ctx: Ctx = Depends(require("planning.read"))):
    """Pauses sans relève possible sur les sites à présence continue (signalement de couverture, jamais un blocage)."""
    from planning_solver.breaks import break_relief_gaps
    p = get_or_404(ctx, m.PlanningPeriod, pid)
    sites = {s.code for s in ctx.db.scalars(select(m.Site).where(m.Site.continuous_presence.is_(True)))}
    if not sites:
        return {"sites": [], "items": []}
    inp = build_input(ctx.db, p)
    return {"sites": sorted(sites), "items": break_relief_gaps(inp, assignments_for_validation(ctx.db, inp, p), sites)}


@router.get("/periods/{pid}/conflicts")
def conflicts(pid: str, ctx: Ctx = Depends(require("planning.read"))):
    p = get_or_404(ctx, m.PlanningPeriod, pid)
    return {"hard_violations": _conflicts(ctx, p.id)}
