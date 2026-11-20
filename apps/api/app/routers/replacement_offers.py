"""Propositions de remplacement : lancement et suivi par le manager, réponse du collaborateur dans « Mon espace ».
Règles détaillées dans app/replacements.py. Droits : le manager (planning.edit) lance et annule ; le collaborateur ne voit et ne
répond qu'aux propositions qui lui sont adressées (compte relié à sa fiche) ; l'entreprise est garantie par la RLS."""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from .. import models as m
from .. import replacements as R
from ..deps import Ctx, audit, get_or_404, require
from ..period_state import ensure_editable, has_official_version

router = APIRouter(tags=["propositions de remplacement"])


def _offer_view(db, o: m.ReplacementOffer, req: m.ReplacementRequest, mine: bool = False) -> dict:
    e = db.get(m.Employee, o.employee_id)
    out = {"id": str(o.id), "request_id": str(req.id), "employee": {"id": str(e.id), "name": e.name} if e else None, "rank": o.rank, "status": o.status,
           "status_label": R.STATUS_LABEL.get(o.status, o.status), "deadline": o.deadline_at.isoformat(), "deadline_label": R.when(db, req.tenant_id, o.deadline_at),
           "responded_at": o.responded_at.isoformat() if o.responded_at else None, "reason": o.reason, "shift": req.shift_label, "created_at": o.created_at.isoformat() if o.created_at else None}
    if mine:
        sh = db.get(m.Shift, req.shift_id) if req.shift_id else None
        p = db.get(m.PlanningPeriod, req.period_id)
        out["details"] = {"day": (req.fingerprint or {}).get("day"), "start": (req.fingerprint or {}).get("start", "")[:5], "end": (req.fingerprint or {}).get("end", "")[:5],
                          "site": db.scalar(select(m.Site.name).where(m.Site.code == (req.fingerprint or {}).get("site"))) or (req.fingerprint or {}).get("site"),
                          "brands": [b for b, _ in (req.fingerprint or {}).get("allocations", [])], "period": p.name if p else None, "exists": sh is not None}
    return out


def _request_view(db, req: m.ReplacementRequest) -> dict:
    offers = list(db.scalars(select(m.ReplacementOffer).where(m.ReplacementOffer.request_id == req.id).order_by(m.ReplacementOffer.created_at)))
    holder = (req.fingerprint or {}).get("employee_id")
    h = db.get(m.Employee, uuid.UUID(holder)) if holder else None
    return {"id": str(req.id), "shift_id": str(req.shift_id) if req.shift_id else None, "period_id": str(req.period_id), "status": req.status,
            "status_label": R.STATUS_LABEL.get(req.status, req.status), "shift": req.shift_label, "holder": h.name if h else None,
            "response_minutes": req.response_minutes, "candidates": len(req.candidates or []), "closed_reason": req.closed_reason,
            "created_at": req.created_at.isoformat() if req.created_at else None, "offers": [_offer_view(db, o, req) for o in offers],
            "pending": next((_offer_view(db, o, req) for o in offers if o.status == "pending"), None)}


class LaunchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start_employee_id: uuid.UUID  # candidat choisi dans le classement ; les suivants sont sollicités dans l'ordre en cas de refus
    response_minutes: int = Field(ge=15, le=7 * 24 * 60)


@router.post("/shifts/{sid}/replacement-requests", status_code=201)
def launch(sid: str, body: LaunchIn, ctx: Ctx = Depends(require("planning.edit"))):
    sh = ctx.db.execute(select(m.Shift).where(m.Shift.id == uuid.UUID(sid)).with_for_update()).scalar_one_or_none() if _is_uuid(sid) else None
    if sh is None:
        raise HTTPException(404, "Introuvable")
    p = ctx.db.get(m.PlanningPeriod, sh.period_id)
    ensure_editable(ctx.db, p.id)
    R.expire_due(ctx.db)
    if ctx.db.scalar(select(m.ReplacementRequest.id).where(m.ReplacementRequest.shift_id == sh.id, m.ReplacementRequest.status == "open")):
        raise HTTPException(409, detail={"code": "already_open", "message": "Une proposition de remplacement est déjà en cours pour ce shift : annulez-la avant d'en lancer une autre."})
    start = R.shift_start(ctx.db, sh)
    if start - R.now() < R.MIN_LEAD:
        raise HTTPException(409, detail={"code": "too_late", "message": "Le shift commence trop tôt pour attendre une réponse : choisissez directement un remplaçant."})
    from .decisions import _ranking, _state
    inp, base = _state(ctx, p)
    emps = {e.code: e for e in ctx.db.scalars(select(m.Employee))}
    r = _ranking(ctx, inp, base, sh, emps)
    ok = [c["employee_uuid"] for c in r["candidates"] if c["status"] == "compatible" and c["employee_uuid"]]
    if str(body.start_employee_id) not in ok:
        raise HTTPException(422, detail={"code": "not_ranked", "message": "Ce collaborateur ne fait pas partie des remplaçants compatibles de ce shift."})
    first = ctx.db.get(m.Employee, body.start_employee_id)
    if R.account(ctx.db, first.id) is None:
        raise HTTPException(422, detail={"code": "no_account", "message": f"{first.name} n'a pas de compte relié à sa fiche : la proposition ne peut pas lui être envoyée. Choisissez-le directement, ou un autre candidat."})
    chain = ok[ok.index(str(body.start_employee_id)):]
    req = m.ReplacementRequest(tenant_id=ctx.tenant_id, period_id=p.id, shift_id=sh.id, status="open", candidates=chain, response_minutes=body.response_minutes,
                               fingerprint=R.fingerprint(ctx.db, sh), shift_label=R.label(ctx.db, sh), created_by=ctx.user.id)
    ctx.db.add(req)
    ctx.db.flush()
    holder = emps.get(r["holder"]) if r.get("holder") else None
    h, mi = divmod(body.response_minutes, 60)
    R._audit(ctx.db, req, "replacement.requested", ctx.user.id, candidates=len(chain), response_minutes=body.response_minutes,
             response_label=(f"{h} h" + (f" {mi:02d}" if mi else "")) if h else f"{mi} min", holder=holder.name if holder else None, by={"id": str(ctx.user.id), "name": ctx.user.name})
    R.offer_next(ctx.db, req, ctx.user.id)
    ctx.db.flush()
    return _request_view(ctx.db, req)


def _is_uuid(x) -> bool:
    try:
        uuid.UUID(str(x))
        return True
    except ValueError:
        return False


@router.get("/shifts/{sid}/replacement-request")
def shift_request(sid: str, ctx: Ctx = Depends(require("planning.read"))):
    """Demande en cours (ou la plus récente) pour ce shift, avec toutes ses propositions."""
    sh = get_or_404(ctx, m.Shift, sid)
    R.expire_due(ctx.db)
    req = ctx.db.scalar(select(m.ReplacementRequest).where(m.ReplacementRequest.shift_id == sh.id).order_by(m.ReplacementRequest.created_at.desc()).limit(1))
    return {"request": _request_view(ctx.db, req) if req else None}


@router.get("/periods/{pid}/replacement-requests")
def period_requests(pid: str, ctx: Ctx = Depends(require("planning.read"))):
    p = get_or_404(ctx, m.PlanningPeriod, pid)
    R.expire_due(ctx.db)
    rows = list(ctx.db.scalars(select(m.ReplacementRequest).where(m.ReplacementRequest.period_id == p.id).order_by(m.ReplacementRequest.created_at.desc()).limit(50)))
    return {"items": [_request_view(ctx.db, r) for r in rows]}


@router.post("/replacement-requests/{rid}/cancel")
def cancel(rid: str, ctx: Ctx = Depends(require("planning.edit"))):
    if not _is_uuid(rid):
        raise HTTPException(404, "Introuvable")
    req0 = ctx.db.get(m.ReplacementRequest, uuid.UUID(rid))
    if req0 is None:
        raise HTTPException(404, "Introuvable")
    if req0.shift_id:
        _lock(ctx, m.Shift, req0.shift_id)
    pend = ctx.db.scalar(select(m.ReplacementOffer.id).where(m.ReplacementOffer.request_id == req0.id, m.ReplacementOffer.status == "pending"))
    if pend:
        _lock(ctx, m.ReplacementOffer, pend)
    req = _lock(ctx, m.ReplacementRequest, req0.id)
    if req.status != "open":
        raise HTTPException(409, detail={"code": "not_open", "message": f"Cette proposition n'est plus en cours ({R.STATUS_LABEL.get(req.status, req.status).lower()})."})
    o = ctx.db.scalar(select(m.ReplacementOffer).where(m.ReplacementOffer.request_id == req.id, m.ReplacementOffer.status == "pending"))
    req.status, req.closed_at, req.closed_reason = "cancelled", R.now(), f"Annulée par {ctx.user.name}"
    if o is not None:
        o.status, o.responded_at, o.reason = "cancelled", R.now(), "Annulée par le manager"
        u = R.account(ctx.db, o.employee_id)
        R._notify(ctx.db, u.id if u else None, "replacement_cancelled", "Proposition de remplacement annulée",
                  f"La proposition pour le shift {req.shift_label} a été annulée par votre responsable. Vous n'avez rien à faire.", {"offer_id": str(o.id), "request_id": str(req.id)})
    R._audit(ctx.db, req, "replacement.cancelled", ctx.user.id, by={"id": str(ctx.user.id), "name": ctx.user.name})
    ctx.db.flush()
    return _request_view(ctx.db, req)


# ---- côté collaborateur ----
def _lock(ctx: Ctx, model, key):
    return ctx.db.execute(select(model).where(model.id == key).with_for_update().execution_options(populate_existing=True)).scalar_one_or_none()


def _my_offer(ctx: Ctx, oid: str) -> m.ReplacementOffer:
    """Verrouillage dans l'ordre commun à toute modification du shift (shift, proposition, demande) : pas d'interblocage avec une
    attribution manuelle, une annulation ou une autre acceptation concurrente."""
    if not _is_uuid(oid) or ctx.user.employee_id is None:
        raise HTTPException(404, "Introuvable")
    o = ctx.db.get(m.ReplacementOffer, uuid.UUID(oid))
    if o is None or o.employee_id != ctx.user.employee_id:  # la proposition d'un autre n'existe pas pour moi
        raise HTTPException(404, "Introuvable")
    if o.shift_id:
        _lock(ctx, m.Shift, o.shift_id)
    return _lock(ctx, m.ReplacementOffer, o.id)


@router.get("/me/replacement-offers")
def my_offers(ctx: Ctx = Depends(require("self.read"))):
    if ctx.user.employee_id is None:
        return {"items": []}
    R.expire_due(ctx.db)
    # propositions des plannings supprimés : retirées de « Mon espace » (conservées en base et dans l'historique), comme le planning lui-même
    rows = list(ctx.db.scalars(select(m.ReplacementOffer).join(m.ReplacementRequest, m.ReplacementRequest.id == m.ReplacementOffer.request_id)
                               .join(m.PlanningPeriod, m.PlanningPeriod.id == m.ReplacementRequest.period_id)
                               .where(m.ReplacementOffer.employee_id == ctx.user.employee_id, m.PlanningPeriod.deleted_at.is_(None))
                               .order_by(m.ReplacementOffer.created_at.desc()).limit(30)))
    items = [_offer_view(ctx.db, o, ctx.db.get(m.ReplacementRequest, o.request_id), mine=True) for o in rows]
    items.sort(key=lambda x: (x["status"] != "pending", x["deadline"] if x["status"] == "pending" else ""))
    return {"items": items}


def _closed(o: m.ReplacementOffer) -> dict:
    msg = {"expired": "Le délai de réponse est dépassé : la proposition a expiré.", "refused": "Vous avez déjà refusé cette proposition.",
           "cancelled": "Cette proposition a été annulée par votre responsable.",
           "invalidated": f"Cette proposition n'est plus valable : {o.reason or 'le shift a changé.'}"}.get(o.status, "Cette proposition n'est plus en attente.")
    return {"code": f"offer_{o.status}", "message": msg + " Votre planning n'a pas été modifié.", "status": o.status}


class RefuseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: Optional[str] = Field(None, max_length=300)


@router.post("/replacement-offers/{oid}/accept")
def accept(oid: str, ctx: Ctx = Depends(require("self.read"))):
    o = _my_offer(ctx, oid)
    req = _lock(ctx, m.ReplacementRequest, o.request_id)
    if o.status == "accepted":  # double clic ou second onglet : même résultat, rien de plus
        return {"accepted": True, "already": True, "message": f"Vous avez déjà accepté ce shift : {req.shift_label}."}
    if o.status == "pending" and o.deadline_at <= R.now():
        R.expire_due(ctx.db)
        ctx.db.refresh(o)
    if o.status != "pending" or req.status != "open":
        return JSONResponse(status_code=409, content={"detail": _closed(o)})
    reason = R.stale_reason(ctx.db, req)
    if reason:  # shift modifié, supprimé ou déjà remplacé : jamais appliquée ; manager et collaborateur prévenus
        R.invalidate(ctx.db, req, reason, ctx.user.id)
        return JSONResponse(status_code=409, content={"detail": {"code": "offer_stale", "status": "invalidated",
                                                                 "message": f"Cette proposition n'est plus valable : {reason} Votre planning n'a pas été modifié."}})
    sh = _lock(ctx, m.Shift, req.shift_id)  # déjà verrouillé par _my_offer
    current = ctx.db.execute(select(m.Assignment).where(m.Assignment.shift_id == sh.id).with_for_update().execution_options(populate_existing=True)).scalar_one_or_none()
    e = ctx.db.execute(select(m.Employee).where(m.Employee.id == o.employee_id).with_for_update()).scalar_one()  # sérialise les acceptations d'un même collaborateur
    p = ctx.db.get(m.PlanningPeriod, req.period_id)
    issues = R.blocking_issues(ctx.db, p, e, sh)
    if issues:  # nouvelle absence, autre shift accepté le même jour, plafond… : jamais appliquée ; candidat suivant sollicité
        txt = " ".join(i["message"] for i in issues[:3])
        o.status, o.responded_at, o.responded_by, o.reason = "invalidated", R.now(), ctx.user.id, txt
        R._audit(ctx.db, req, "replacement.invalidated", ctx.user.id, reason=f"Acceptation impossible pour {e.name} : {txt}", employee={"id": str(e.id), "name": e.name})
        ctx.db.flush()
        R.offer_next(ctx.db, req, ctx.user.id, o.rank)
        return JSONResponse(status_code=409, content={"detail": {"code": "offer_blocked", "status": "invalidated", "issues": [i["message"] for i in issues],
                                                                 "message": f"Vous ne pouvez pas reprendre ce shift : {txt} Votre planning n'a pas été modifié ; votre responsable en est informé par le suivi de la proposition."}})
    # transfert en une opération : même traitement qu'une attribution manuelle (verrouillée, plafond, rappels)
    from ..history import assignment_detail
    from ..limits import guard_monthly_cap, month_minutes
    from ..optimize import ensure_frozen
    from .. import regularize
    months = [(sh.day.year, sh.day.month)]
    before = month_minutes(ctx.db, [e.id], months)
    from_emp = ctx.db.get(m.Employee, current.employee_id) if current else None
    if current is not None:
        current.employee_id, current.source, current.locked = e.id, "manual", True
        a = current
        for lk in ctx.db.scalars(select(m.LockedAssignment).where(m.LockedAssignment.assignment_id == a.id)):
            ctx.db.delete(lk)
    else:
        from ..services_bridge import build_input
        slot = next((s for s in build_input(ctx.db, p).slots if s.id == sh.slot_key), None)
        a = m.Assignment(tenant_id=ctx.tenant_id, period_id=p.id, shift_id=sh.id, employee_id=e.id, source="manual", locked=True)
        ctx.db.add(a)
        ctx.db.flush()
        ctx.db.add(m.Break(tenant_id=ctx.tenant_id, assignment_id=a.id, minutes=sh.break_minutes, paid=False))
        for brand, minutes in (slot.allocations if slot else {}).items():
            ctx.db.add(m.BrandAllocation(tenant_id=ctx.tenant_id, assignment_id=a.id, brand_code=brand, minutes=minutes))
    ctx.db.add(m.LockedAssignment(tenant_id=ctx.tenant_id, assignment_id=a.id, locked_by=ctx.user.id, reason="remplacement accepté"))
    o.status, o.responded_at, o.responded_by = "accepted", R.now(), ctx.user.id
    req.status, req.closed_at, req.closed_reason = "filled", R.now(), f"Acceptée par {e.name}"  # avant l'écriture : la demande n'est plus « ouverte »
    ctx.db.flush()
    guard_monthly_cap(ctx.db, ctx.tenant_id, before, [e.id], months)
    ensure_frozen(ctx.db, p)
    regularize.resolve(ctx.db, p.id)
    audit(ctx, "assignment.replacement", "assignment", a.id, assignment_detail(ctx.db, sh, from_emp, e, reason="Proposition de remplacement acceptée", request_id=str(req.id)))
    R._audit(ctx.db, req, "replacement.accepted", ctx.user.id, employee={"id": str(e.id), "name": e.name}, holder=from_emp.name if from_emp else None)
    official = has_official_version(ctx.db, p.id)
    later = " Le planning publié sera mis à jour à la prochaine publication." if official else ""
    R._notify(ctx.db, req.created_by, "replacement_update", "Remplacement accepté",
              f"{e.name} a accepté de reprendre le shift {req.shift_label}" + (f" (à la place de {from_emp.name})" if from_emp else "") + "." +
              (" Une version validée ou publiée existe : publiez une nouvelle version pour informer l'équipe." if official else ""),
              {"request_id": str(req.id), "period_id": str(p.id), "month": p.start_date.strftime("%Y-%m")})
    if from_emp is not None:
        hu = R.account(ctx.db, from_emp.id)
        R._notify(ctx.db, hu.id if hu else None, "replacement_update", "Votre shift est repris",
                  f"Votre shift du {req.shift_label} est repris par {e.name}.{later}", {"request_id": str(req.id)})
    return {"accepted": True, "already": False, "message": f"C'est noté : vous reprenez le shift du {req.shift_label}.{later}"}


@router.post("/replacement-offers/{oid}/refuse")
def refuse(oid: str, body: RefuseIn, ctx: Ctx = Depends(require("self.read"))):
    o = _my_offer(ctx, oid)
    req = _lock(ctx, m.ReplacementRequest, o.request_id)
    if o.status == "refused":
        return {"refused": True, "already": True, "message": "Vous avez déjà refusé cette proposition."}
    if o.status == "pending" and o.deadline_at <= R.now():
        R.expire_due(ctx.db)
        ctx.db.refresh(o)
    if o.status != "pending":
        return JSONResponse(status_code=409, content={"detail": _closed(o)})
    e = ctx.db.get(m.Employee, o.employee_id)
    o.status, o.responded_at, o.responded_by, o.reason = "refused", R.now(), ctx.user.id, (body.reason or "").strip() or None
    R._audit(ctx.db, req, "replacement.refused", ctx.user.id, employee={"id": str(e.id), "name": e.name}, reason=o.reason, rank=o.rank)
    ctx.db.flush()
    if req.status == "open":
        reason = R.stale_reason(ctx.db, req)
        if reason:
            R.invalidate(ctx.db, req, reason, ctx.user.id)
        else:
            R.offer_next(ctx.db, req, ctx.user.id, o.rank)
    return {"refused": True, "already": False, "message": "C'est noté : vous ne reprenez pas ce shift. Votre planning n'a pas été modifié."}


__all__ = ["router"]
