"""Calendrier d'indisponibilités, horaires par marque, ajout manuel d'un shift et compatibilité du planning avec les paramètres."""
import uuid
from datetime import date
from typing import Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select

from planning_solver.compat import compatibility
from planning_solver.timecalc import shift_hours

from .. import models as m
from ..deps import Ctx, audit, get_or_404, require
from ..history import assignment_detail
from ..period_state import ensure_editable
from ..limits import guard_monthly_cap, month_minutes
from ..optimize import ensure_frozen, freeze_period
from ..services_bridge import assignments_for_validation, brand_schedules, build_input, params_mode, tenant_cap
from ..frozen import differences
from planning_solver.model import fmt_minutes
from ..approval import override_refusal
from .planning import _conflicts

router = APIRouter(tags=["disponibilités et horaires"])


@router.get("/employees/{eid}/availability")
def availability(eid: str, ctx: Ctx = Depends(require("employees.read"))):
    e = get_or_404(ctx, m.Employee, eid)
    un = list(ctx.db.scalars(select(m.Unavailability).where(m.Unavailability.employee_id == e.id)))
    leaves = list(ctx.db.scalars(select(m.LeaveRequest).where(m.LeaveRequest.employee_id == e.id, m.LeaveRequest.status == "approved")))
    return {"dates": sorted(u.on_date.isoformat() for u in un if u.on_date), "weekdays": sorted({u.weekday for u in un if u.weekday is not None}),
            "leaves": [{"start": lv.start_date.isoformat(), "end": lv.end_date.isoformat(), "kind": lv.kind} for lv in leaves]}


class DatesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dates: List[date] = Field(max_length=800)


@router.put("/employees/{eid}/unavailable-dates")
def set_unavailable_dates(eid: str, body: DatesIn, ctx: Ctx = Depends(require("availability.write"))):
    """Remplace les jours d'indisponibilité datés du collaborateur (les indisponibilités hebdomadaires récurrentes sont conservées)."""
    e = get_or_404(ctx, m.Employee, eid)
    today = date.today()
    if any(abs((d - today).days) > 800 for d in body.dates):
        raise HTTPException(422, "Date trop éloignée")
    wanted = sorted(set(body.dates))
    existing = {u.on_date: u for u in ctx.db.scalars(select(m.Unavailability).where(m.Unavailability.employee_id == e.id, m.Unavailability.on_date.is_not(None)))}
    removed = [d for d in existing if d not in wanted]
    added = [d for d in wanted if d not in existing]
    if removed:
        ctx.db.execute(delete(m.Unavailability).where(m.Unavailability.employee_id == e.id, m.Unavailability.on_date.in_(removed)))
    for d in added:
        ctx.db.add(m.Unavailability(tenant_id=ctx.tenant_id, employee_id=e.id, on_date=d, reason="calendrier"))
    if added or removed:
        audit(ctx, "availability.dates", "employee", e.id, {"added": [d.isoformat() for d in added], "removed": [d.isoformat() for d in removed]})
    return {"dates": [d.isoformat() for d in wanted]}


@router.get("/brand-schedules")
def schedules(ctx: Ctx = Depends(require("referential.read"))):
    return brand_schedules(ctx.db)


class AddIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    employee_id: uuid.UUID
    day: date
    brand_code: str = Field(max_length=64)
    template_id: uuid.UUID


@router.post("/periods/{pid}/assignments", status_code=201)
def add_assignment(pid: str, body: AddIn, ctx: Ctx = Depends(require("planning.edit"))):
    """Ajoute un shift à la main. Refusé si la marque n'est pas autorisée au collaborateur, si l'horaire n'appartient pas à la marque,
    si le collaborateur est indisponible ou déjà affecté ce jour-là. L'affectation est verrouillée (jamais modifiée en silence)."""
    p = get_or_404(ctx, m.PlanningPeriod, pid)
    ensure_editable(ctx.db, p.id)
    e = ctx.db.get(m.Employee, body.employee_id)
    if e is None or not e.active:
        raise HTTPException(422, "Collaborateur inconnu ou inactif")
    if e.deleted_at is not None:
        raise HTTPException(422, f"{e.name} a été supprimé·e de l'équipe : plus aucun shift ne peut lui être attribué (réintégrez-le d'abord).")
    if not (p.start_date <= body.day <= p.end_date):
        raise HTTPException(422, "Date hors de la période")
    if body.brand_code not in (e.brands or {}):
        raise HTTPException(422, f"{body.brand_code} n'est pas autorisée pour {e.name}.")
    sched = brand_schedules(ctx.db).get(body.brand_code, [])
    t = next((x for x in sched if x["template_id"] == str(body.template_id)), None)
    if t is None:
        ok = ", ".join(f"{x['start'][:5]}–{x['end'][:5]}" for x in sched) or "aucun"
        raise HTTPException(422, f"Horaire non autorisé pour {body.brand_code}. Horaires autorisés : {ok}.")
    inp = build_input(ctx.db, p)
    se = next((x for x in inp.employees if x.id == e.code), None)
    if se is not None and se.blocked(body.day):
        raise HTTPException(422, f"{e.name} est indisponible le {body.day.isoformat()}.")
    before_minutes = month_minutes(ctx.db, [e.id], [(body.day.year, body.day.month)])
    same_day = ctx.db.scalars(select(m.Assignment).join(m.Shift, m.Shift.id == m.Assignment.shift_id)
                              .where(m.Assignment.employee_id == e.id, m.Shift.day == body.day)).all()
    if same_day:
        raise HTTPException(409, f"{e.name} est déjà affecté·e le {body.day.isoformat()} (une seule affectation par jour).")
    from datetime import time as _t
    start, end = _t.fromisoformat(t["start"]), _t.fromisoformat(t["end"])
    h = shift_hours(body.day, start, end, t["break_minutes"])
    sh = m.Shift(tenant_id=ctx.tenant_id, period_id=p.id, slot_key=f"MANUAL|{uuid.uuid4().hex[:10]}|{body.day.isoformat()}", day=body.day,
                 site_code=t["site"], start_time=start, end_time=end, break_minutes=t["break_minutes"],
                 presence_minutes=h.presence_minutes, effective_minutes=h.effective_minutes)
    ctx.db.add(sh)
    ctx.db.flush()
    a = m.Assignment(tenant_id=ctx.tenant_id, period_id=p.id, shift_id=sh.id, employee_id=e.id, source="manual", locked=True)
    ctx.db.add(a)
    ctx.db.flush()
    ctx.db.add(m.Break(tenant_id=ctx.tenant_id, assignment_id=a.id, minutes=t["break_minutes"], paid=False))
    ctx.db.add(m.BrandAllocation(tenant_id=ctx.tenant_id, assignment_id=a.id, brand_code=body.brand_code, minutes=h.effective_minutes))
    ctx.db.add(m.LockedAssignment(tenant_id=ctx.tenant_id, assignment_id=a.id, locked_by=ctx.user.id, reason="ajout manuel"))
    ctx.db.flush()
    guard_monthly_cap(ctx.db, ctx.tenant_id, before_minutes, [e.id], [(body.day.year, body.day.month)])
    ensure_frozen(ctx.db, p)
    audit(ctx, "assignment.manual_add", "assignment", a.id, assignment_detail(ctx.db, sh, None, e, brand=body.brand_code, template=t["template"]))
    return {"assignment_id": str(a.id), "shift_id": str(sh.id), "conflicts": _conflicts(ctx, p.id)}


@router.delete("/assignments/{aid}", status_code=204)
def delete_assignment(aid: str, force: bool = False, reason: Optional[str] = None, ctx: Ctx = Depends(require("planning.edit"))):
    """Retire un shift du collaborateur (le shift redevient disponible). Verrouillé : 409, sauf `force` par un rôle d'administration."""
    a = get_or_404(ctx, m.Assignment, aid)
    ensure_editable(ctx.db, a.period_id)
    refusal = override_refusal(ctx, (a.employee_id,))
    if a.locked and not force:
        raise HTTPException(409, detail={"code": "locked", "can_override": refusal is None, "refusal": refusal, "message": "Affectation verrouillée : déverrouillez-la d'abord, ou confirmez le retrait."})
    if a.locked and refusal:
        raise HTTPException(403, detail={"code": "forbidden", "can_override": False, "message": refusal})
    sh = ctx.db.get(m.Shift, a.shift_id)
    who = ctx.db.get(m.Employee, a.employee_id)
    detail = assignment_detail(ctx.db, sh, who, None, forced=bool(a.locked), reason=reason)
    ctx.db.delete(a)
    ctx.db.flush()
    if sh is not None and sh.slot_key.startswith("MANUAL|"):
        ctx.db.delete(sh)
    audit(ctx, "assignment.manual_remove", "assignment", aid, detail)


def compat_report(ctx: Ctx, p: m.PlanningPeriod, params: str = "plan") -> dict:
    """Incompatibilités du planning avec SES paramètres (params="plan", par défaut) ou avec les paramètres actuels (params="current",
    aperçu avant de les appliquer). Lecture seule : rien n'est modifié."""
    flags = {"params": "current", "cap": "current"} if params == "current" else {}
    inp = build_input(ctx.db, p, flags)
    assigns = assignments_for_validation(ctx.db, inp, p)
    res = compatibility(inp, assigns)
    rows = list(ctx.db.scalars(select(m.Assignment).where(m.Assignment.period_id == p.id)))
    keys = {sh.id: sh.slot_key for sh in ctx.db.scalars(select(m.Shift).where(m.Shift.period_id == p.id))}
    site_names = {x.code: x.name for x in ctx.db.scalars(select(m.Site))}
    ids = {e.code: str(e.id) for e in ctx.db.scalars(select(m.Employee))}
    for it in res["items"]:
        it["employee_uuid"] = ids.get(it.get("employee_id") or "")
        for sh in it["shifts"]:
            sh["site_name"] = site_names.get(sh["site"], sh["site"])
    flagged_slots = {sh["slot_id"] for it in res["items"] for sh in it["shifts"]}
    mode = params_mode(p, flags)
    out = {"hard": res["hard"], "soft": res["soft"], "items": res["items"], "checked": res["checked"],
           "flagged_assignment_ids": [str(a.id) for a in rows if keys.get(a.shift_id) in flagged_slots],
           "locked": sum(1 for a in rows if a.locked), "unlocked": sum(1 for a in rows if not a.locked), "has_plan": bool(rows),
           "compatible": not res["items"], "params": {"mode": mode, "requested": params, "frozen_at": p.frozen_at.isoformat() if p.frozen_at else None,
                                                      "source": p.frozen_source, "monthly_cap_minutes": inp.config.monthly_cap_minutes}}
    cap = tenant_cap(ctx.db, ctx.tenant_id)
    if params != "current" and cap is not None and inp.config.monthly_cap_minutes != cap and assigns:
        # planning établi avant le plafond actuel : signalé (jamais compté comme incompatibilité de ce planning ni corrigé en silence)
        over: Dict[str, int] = {}
        months = {(a.day.year, a.day.month) for a in assigns}
        per = month_minutes(ctx.db, [a.employee_id for a in rows], months)
        names = {e.id: e.name for e in ctx.db.scalars(select(m.Employee))}
        for (eid, mk), v in per.items():
            if v > cap:
                over[names.get(eid, "—")] = max(over.get(names.get(eid, "—"), 0), v)
        out["cap_notice"] = {"cap_minutes": cap, "plan_cap_minutes": inp.config.monthly_cap_minutes,
                             "over": [{"employee": n, "minutes": v, "label": fmt_minutes(v)} for n, v in sorted(over.items(), key=lambda kv: -kv[1])]}
    # collaborateurs supprimés après la création du planning : leurs affectations restent (historique), signalées sans être des incompatibilités
    removed = []
    for e in ctx.db.scalars(select(m.Employee).where(m.Employee.deleted_at.is_not(None))):
        n = sum(1 for a in assigns if a.employee_id == e.code and e.removed_on and a.day >= e.removed_on)
        if n:
            removed.append({"employee": e.name, "removed_on": e.removed_on.isoformat(), "assignments": n})
    out["removed_notice"] = removed
    return out


@router.get("/periods/{pid}/compatibility")
def compat(pid: str, params: Literal["plan", "current"] = "plan", ctx: Ctx = Depends(require("planning.read"))):
    """Incompatibilités détaillées (collaborateur, date, horaires, site, règle, raison ; obligatoire ou préférence)."""
    return compat_report(ctx, get_or_404(ctx, m.PlanningPeriod, pid), params)


@router.get("/periods/{pid}/params")
def period_params(pid: str, ctx: Ctx = Depends(require("planning.read"))):
    """Paramètres conservés par ce planning et différences avec les paramètres actuels (fiches, règles)."""
    p = get_or_404(ctx, m.PlanningPeriod, pid)
    cap = {}
    build_input(ctx.db, p, {"params": "current"}, capture=cap)
    diffs = differences(p.frozen_params, cap["employees"], cap["config"], cap["names"]) if p.frozen_params else []
    return {"frozen": bool(p.frozen_params), "frozen_at": p.frozen_at.isoformat() if p.frozen_at else None, "source": p.frozen_source,
            "differences": diffs, "current_cap_minutes": tenant_cap(ctx.db, ctx.tenant_id),
            "plan_cap_minutes": (p.frozen_params or {}).get("config", {}).get("monthly_cap_minutes") if p.frozen_params else None,
            "generation_run_id": (p.frozen_params or {}).get("generation_run_id"),
            "weights": (p.frozen_params or {}).get("config", {}).get("weights")}


class ApplyParamsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm: bool = False


@router.post("/periods/{pid}/params/apply-current")
def apply_current_params(pid: str, body: ApplyParamsIn, ctx: Ctx = Depends(require("planning.edit"))):
    """Action EXPLICITE : ce planning adopte les paramètres actuels. Aucune affectation n'est modifiée ; les incompatibilités qui en
    résultent sont listées (à corriger à la main ou par une réoptimisation)."""
    p = get_or_404(ctx, m.PlanningPeriod, pid)
    ensure_editable(ctx.db, p.id)
    if not body.confirm:
        raise HTTPException(422, "Confirmation requise : les paramètres actuels remplaceront ceux conservés par ce planning.")
    before = p.frozen_at.isoformat() if p.frozen_at else None
    freeze_period(ctx.db, p, "apply", cap_used=tenant_cap(ctx.db, ctx.tenant_id))
    ctx.db.flush()
    rep = compat_report(ctx, p)
    audit(ctx, "period.params_apply_current", "period", p.id, {"period": p.name, "previous_frozen_at": before, "incompatibilities": len(rep["items"])})
    return rep
