"""Demandes des collaborateurs et circuit d'approbation.

Un collaborateur (compte relié à sa fiche) demande un congé, une absence d'une journée ou d'une partie de journée, ou un échange de shifts
avec un collègue. Un échange demande d'abord l'accord du collègue. Rien n'est appliqué sans la décision d'un responsable ; l'approbation
passe par les mêmes chemins que les écrans de gestion (indisponibilités, absences partielles, échange contrôlé avec dérogation tracée).
Un congé ou une absence approuvés ne retirent aucun shift : les shifts concernés sont listés et une révision est proposée si le planning
est officiel, comme pour une absence déclarée par un responsable."""
import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select

from .. import models as m
from ..deps import Ctx, audit, get_or_404, require
from ..period_state import ensure_editable
from ..rbac import has_permission

router = APIRouter(tags=["demandes des collaborateurs"])

LEAVE_KINDS = {"conge": "Congé", "formation": "Formation", "maladie": "Maladie", "autre": "Autre"}
STATUS = {"pending": "En attente du responsable", "awaiting_colleague": "En attente du collègue", "approved": "Approuvée", "refused": "Refusée",
          "declined": "Refusée par le collègue", "cancelled": "Annulée"}
DAYS = ("lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim.")


class RequestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["leave", "absence", "swap"]
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    leave_kind: str = Field("conge", pattern="^(conge|formation|maladie|autre)$")
    on_date: Optional[date] = None
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    my_day: Optional[date] = None
    colleague_id: Optional[uuid.UUID] = None
    colleague_day: Optional[date] = None
    note: Optional[str] = Field(None, max_length=500)

    @model_validator(mode="after")
    def _k(self):
        if self.kind == "leave":
            if not self.start_date or not self.end_date or self.end_date < self.start_date:
                raise ValueError("congé : date de début et date de fin (la fin ne précède pas le début)")
            if (self.end_date - self.start_date).days > 62:
                raise ValueError("congé : 63 jours au plus par demande")
        elif self.kind == "absence":
            if not self.on_date:
                raise ValueError("absence : date obligatoire")
            if (self.start_time is None) != (self.end_time is None):
                raise ValueError("absence partielle : heure de début et heure de fin")
            if self.start_time is not None and self.end_time <= self.start_time:
                raise ValueError("absence partielle : la fin doit suivre le début")
        else:
            if not (self.my_day and self.colleague_id and self.colleague_day):
                raise ValueError("échange : votre jour, le collègue et son jour")
        return self


def _me(ctx: Ctx) -> m.Employee:
    e = ctx.db.get(m.Employee, ctx.user.employee_id) if ctx.user.employee_id else None
    if e is None or e.deleted_at is not None:
        raise HTTPException(403, "Votre compte n'est pas relié à une fiche collaborateur : demandez-le à votre responsable.")
    return e


def _shift_on(ctx: Ctx, eid, day: date):
    """Affectation du planning de travail de `eid` ce jour-là (la première par heure de début)."""
    return ctx.db.execute(select(m.Assignment, m.Shift).join(m.Shift, m.Shift.id == m.Assignment.shift_id)
                          .where(m.Assignment.employee_id == eid, m.Shift.day == day).order_by(m.Shift.start_time).limit(1)).first()


def _label(sh: m.Shift, sites: dict) -> str:
    return f"{DAYS[sh.day.weekday()]} {sh.day:%d/%m} · {sites.get(sh.site_code, sh.site_code)} · {sh.start_time:%H:%M}–{sh.end_time:%H:%M}"


def _users_of(ctx: Ctx, eid) -> list:
    return list(ctx.db.scalars(select(m.User).where(m.User.employee_id == eid, m.User.is_active.is_(True))))


def _notify(ctx: Ctx, users, title: str, body: str, payload: dict) -> None:
    for u in users:
        ctx.db.add(m.Notification(tenant_id=ctx.tenant_id, user_id=u.id, kind="request", title=title, body=body, payload=payload))


def _approvers(ctx: Ctx, kind: str) -> list:
    perm = "planning.edit" if kind == "swap" else "availability.write"
    return [u for u in ctx.db.scalars(select(m.User).where(m.User.is_active.is_(True))) if has_permission(u.role, perm) and u.id != ctx.user.id]


def _summary(r: m.EmployeeRequest, names: dict) -> str:
    P = r.payload or {}
    if r.kind == "leave":
        return f"{LEAVE_KINDS.get(P.get('leave_kind'), 'Congé')} du {date.fromisoformat(P['start_date']):%d/%m/%Y} au {date.fromisoformat(P['end_date']):%d/%m/%Y}"
    if r.kind == "absence":
        d = date.fromisoformat(P["on_date"])
        return f"Absence le {d:%d/%m/%Y}" + (f" de {P['start_time']} à {P['end_time']}" if P.get("start_time") else " (journée entière)")
    return f"Échange : {P.get('mine_label')} ↔ {names.get(str(r.colleague_employee_id), '—')} · {P.get('theirs_label')}"


def _out(ctx: Ctx, r: m.EmployeeRequest, names: dict, impact: bool = False) -> dict:
    d = {"id": str(r.id), "kind": r.kind, "status": r.status, "status_label": STATUS.get(r.status, r.status), "employee_id": str(r.employee_id),
         "employee": names.get(str(r.employee_id), "—"), "colleague_id": str(r.colleague_employee_id) if r.colleague_employee_id else None,
         "colleague": names.get(str(r.colleague_employee_id)) if r.colleague_employee_id else None, "summary": _summary(r, names), "note": r.note,
         "payload": r.payload, "created_at": r.created_at, "decided_at": r.decided_at, "decision_note": r.decision_note, "result": r.result}
    if impact and r.kind in ("leave", "absence") and r.status == "pending":
        P = r.payload
        lo = date.fromisoformat(P.get("start_date") or P["on_date"])
        hi = date.fromisoformat(P.get("end_date") or P["on_date"])
        sites = {s.code: s.name for s in ctx.db.scalars(select(m.Site))}
        rows = ctx.db.execute(select(m.Assignment, m.Shift).join(m.Shift, m.Shift.id == m.Assignment.shift_id)
                              .where(m.Assignment.employee_id == r.employee_id, m.Shift.day >= lo, m.Shift.day <= hi).order_by(m.Shift.day, m.Shift.start_time)).all()
        if r.kind == "absence" and P.get("start_time"):
            a0, a1 = time.fromisoformat(P["start_time"]), time.fromisoformat(P["end_time"])
            rows = [(a, sh) for a, sh in rows if sh.start_time < a1 and a0 < (sh.end_time if sh.end_time > sh.start_time else time(23, 59))]
        d["impact"] = [_label(sh, sites) for _a, sh in rows]
    if r.kind == "swap" and r.status in ("pending", "awaiting_colleague"):  # l'échange est-il toujours possible tel que demandé ?
        A, B = ctx.db.get(m.Assignment, uuid.UUID(r.payload["mine"])), ctx.db.get(m.Assignment, uuid.UUID(r.payload["theirs"]))
        d["stale"] = not (A and B and A.employee_id == r.employee_id and B.employee_id == r.colleague_employee_id)
    return d


def _names(ctx: Ctx) -> dict:
    return {str(e.id): e.name for e in ctx.db.scalars(select(m.Employee))}


# ---------- côté collaborateur ----------
@router.get("/me/requests")
def my_requests(ctx: Ctx = Depends(require("self.read"))):
    e = _me(ctx)
    names = _names(ctx)
    mine = ctx.db.scalars(select(m.EmployeeRequest).where(m.EmployeeRequest.employee_id == e.id).order_by(m.EmployeeRequest.created_at.desc()).limit(100))
    received = ctx.db.scalars(select(m.EmployeeRequest).where(m.EmployeeRequest.colleague_employee_id == e.id)
                              .order_by(m.EmployeeRequest.created_at.desc()).limit(50))
    colleagues = [{"id": str(x.id), "name": x.name} for x in ctx.db.scalars(select(m.Employee).where(m.Employee.active.is_(True), m.Employee.deleted_at.is_(None),
                                                                                                   m.Employee.id != e.id).order_by(m.Employee.name))]
    return {"employee": {"id": str(e.id), "name": e.name}, "mine": [_out(ctx, r, names) for r in mine], "received": [_out(ctx, r, names) for r in received],
            "colleagues": colleagues}


@router.post("/me/requests", status_code=201)
def create_request(body: RequestIn, ctx: Ctx = Depends(require("self.read"))):
    e = _me(ctx)
    payload: dict = {}
    colleague = None
    status = "pending"
    if body.kind == "leave":
        payload = {"start_date": body.start_date.isoformat(), "end_date": body.end_date.isoformat(), "leave_kind": body.leave_kind}
    elif body.kind == "absence":
        payload = {"on_date": body.on_date.isoformat(), "start_time": body.start_time.strftime("%H:%M") if body.start_time else None,
                   "end_time": body.end_time.strftime("%H:%M") if body.end_time else None}
    else:
        colleague = ctx.db.get(m.Employee, body.colleague_id)
        if colleague is None or colleague.id == e.id or not colleague.active or colleague.deleted_at is not None:
            raise HTTPException(422, "Collègue inconnu")
        mine, theirs = _shift_on(ctx, e.id, body.my_day), _shift_on(ctx, colleague.id, body.colleague_day)
        if mine is None:
            raise HTTPException(422, f"Vous n'avez pas de shift le {body.my_day:%d/%m/%Y}.")
        if theirs is None:
            raise HTTPException(422, f"{colleague.name} n'a pas de shift le {body.colleague_day:%d/%m/%Y}.")
        if mine[0].period_id != theirs[0].period_id:
            raise HTTPException(422, "Les deux shifts doivent appartenir au même planning mensuel.")
        sites = {s.code: s.name for s in ctx.db.scalars(select(m.Site))}
        payload = {"mine": str(mine[0].id), "theirs": str(theirs[0].id), "period_id": str(mine[0].period_id),
                   "mine_label": _label(mine[1], sites), "theirs_label": _label(theirs[1], sites)}
        status = "awaiting_colleague"
    r = m.EmployeeRequest(tenant_id=ctx.tenant_id, employee_id=e.id, kind=body.kind, payload=payload, note=body.note, status=status,
                          colleague_employee_id=colleague.id if colleague else None, created_by=ctx.user.id)
    ctx.db.add(r)
    ctx.db.flush()
    names = _names(ctx)
    text = _summary(r, names)
    if colleague is not None:
        _notify(ctx, _users_of(ctx, colleague.id), f"Proposition d'échange de {e.name}", text, {"request_id": str(r.id)})
    else:
        _notify(ctx, _approvers(ctx, r.kind), f"Demande de {e.name}", text, {"request_id": str(r.id)})
    audit(ctx, "request.create", "request", r.id, {"kind": r.kind, "summary": text})
    return _out(ctx, r, names)


@router.post("/me/requests/{rid}/cancel")
def cancel_request(rid: str, ctx: Ctx = Depends(require("self.read"))):
    e = _me(ctx)
    r = get_or_404(ctx, m.EmployeeRequest, rid)
    if r.employee_id != e.id:
        raise HTTPException(404, "Introuvable")
    if r.status not in ("pending", "awaiting_colleague"):
        raise HTTPException(409, "Cette demande a déjà été traitée.")
    r.status = "cancelled"
    audit(ctx, "request.cancel", "request", r.id, {})
    return _out(ctx, r, _names(ctx))


class AnswerIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    accept: bool


@router.post("/me/requests/{rid}/answer")
def answer_request(rid: str, body: AnswerIn, ctx: Ctx = Depends(require("self.read"))):
    """Réponse du collègue à une proposition d'échange : l'accord transmet la demande au responsable, le refus la clôt."""
    e = _me(ctx)
    r = get_or_404(ctx, m.EmployeeRequest, rid)
    if r.colleague_employee_id != e.id:
        raise HTTPException(404, "Introuvable")
    if r.status != "awaiting_colleague":
        raise HTTPException(409, "Cette proposition a déjà reçu une réponse ou a été annulée.")
    r.status = "pending" if body.accept else "declined"
    r.colleague_answered_at = datetime.now(timezone.utc)
    names = _names(ctx)
    text = _summary(r, names)
    _notify(ctx, _users_of(ctx, r.employee_id), f"{e.name} a {'accepté' if body.accept else 'refusé'} votre proposition d'échange", text, {"request_id": str(r.id)})
    if body.accept:
        _notify(ctx, _approvers(ctx, "swap"), f"Échange à valider : {names.get(str(r.employee_id))} et {e.name}", text, {"request_id": str(r.id)})
    audit(ctx, "request.answer", "request", r.id, {"accept": body.accept})
    return _out(ctx, r, names)


# ---------- côté responsable ----------
@router.get("/requests")
def list_requests(status: Optional[str] = "open", ctx: Ctx = Depends(require("employees.read"))):
    """Demandes à traiter (« open » : en attente du responsable ou du collègue) ou historique (« all »)."""
    q = select(m.EmployeeRequest).order_by(m.EmployeeRequest.created_at.desc()).limit(300)
    if status == "open":
        q = q.where(m.EmployeeRequest.status.in_(["pending", "awaiting_colleague"]))
    names = _names(ctx)
    return [_out(ctx, r, names, impact=True) for r in ctx.db.scalars(q)]


class DecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approve: bool
    note: Optional[str] = Field(None, max_length=500)
    force: bool = False  # échange : confirmation des alertes dérogeables (mêmes règles qu'un échange fait à l'écran)


@router.post("/requests/{rid}/decide")
def decide(rid: str, body: DecisionIn, ctx: Ctx = Depends(require("employees.read"))):
    r = get_or_404(ctx, m.EmployeeRequest, rid)
    perm = "planning.edit" if r.kind == "swap" else "availability.write"
    if not has_permission(ctx.user.role, perm):
        raise HTTPException(403, f"Permission requise : {perm}")
    if r.status != "pending":
        raise HTTPException(409, "Cette demande n'est pas en attente de décision" + (" (accord du collègue attendu)." if r.status == "awaiting_colleague" else "."))
    if ctx.user.employee_id is not None and ctx.user.employee_id in (r.employee_id, r.colleague_employee_id):
        raise HTTPException(403, "Cette demande vous concerne : un autre responsable doit la traiter.")
    e = ctx.db.get(m.Employee, r.employee_id)
    names = _names(ctx)
    result: dict = {}
    if body.approve:
        P = r.payload
        if r.kind == "leave":
            lo, hi = date.fromisoformat(P["start_date"]), date.fromisoformat(P["end_date"])
            lv = m.LeaveRequest(tenant_id=ctx.tenant_id, employee_id=e.id, start_date=lo, end_date=hi, kind=P.get("leave_kind", "conge"), status="approved")
            ctx.db.add(lv)
            ctx.db.flush()
            from ..revision import propose_revision
            days = [lo + timedelta(days=k) for k in range((hi - lo).days + 1)]
            result = {"leave_id": str(lv.id), "revisions": propose_revision(ctx.db, ctx.tenant_id, e, days, ctx.user.id)}
        elif r.kind == "absence":
            d = date.fromisoformat(P["on_date"])
            if P.get("start_time"):
                pa = m.PartialAbsence(tenant_id=ctx.tenant_id, employee_id=e.id, on_date=d, start_time=time.fromisoformat(P["start_time"]),
                                      end_time=time.fromisoformat(P["end_time"]), reason=r.note or "demande du collaborateur")
                ctx.db.add(pa)
                ctx.db.flush()
                result = {"partial_absence_id": str(pa.id)}
            else:
                have = ctx.db.scalar(select(m.Unavailability.id).where(m.Unavailability.employee_id == e.id, m.Unavailability.on_date == d))
                if have is None:
                    ctx.db.add(m.Unavailability(tenant_id=ctx.tenant_id, employee_id=e.id, on_date=d, reason="demande du collaborateur"))
                    ctx.db.flush()
                from ..revision import propose_revision
                result = {"revisions": propose_revision(ctx.db, ctx.tenant_id, e, [d], ctx.user.id)}
        else:
            from .manual_shifts import perform_swap
            A = ctx.db.execute(select(m.Assignment).where(m.Assignment.id == uuid.UUID(P["mine"])).with_for_update()).scalar_one_or_none()
            B = ctx.db.execute(select(m.Assignment).where(m.Assignment.id == uuid.UUID(P["theirs"])).with_for_update()).scalar_one_or_none()
            if not (A and B and A.employee_id == r.employee_id and B.employee_id == r.colleague_employee_id):
                raise HTTPException(409, detail={"code": "stale", "issues": [], "can_override": False,
                                                 "message": "Le planning a changé depuis la demande : ces shifts ne sont plus tenus par ces collaborateurs. Refusez la demande ; le collaborateur pourra en refaire une."})
            p = ctx.db.get(m.PlanningPeriod, A.period_id)
            ensure_editable(ctx.db, p.id)
            result = perform_swap(ctx, p, A, B, body.force, body.note or r.note, origin="demande d'échange approuvée")
    r.status = "approved" if body.approve else "refused"
    r.decided_by, r.decided_at, r.decision_note = ctx.user.id, datetime.now(timezone.utc), body.note
    r.result = {k: v for k, v in result.items() if k != "conflicts"}
    text = _summary(r, names) + (f" — {body.note}" if body.note else "")
    title = f"Demande {'approuvée' if body.approve else 'refusée'}"
    _notify(ctx, _users_of(ctx, r.employee_id), title, text, {"request_id": str(r.id)})
    if r.colleague_employee_id:
        _notify(ctx, _users_of(ctx, r.colleague_employee_id), title, text, {"request_id": str(r.id)})
    audit(ctx, "request.approve" if body.approve else "request.refuse", "request", r.id, {"summary": _summary(r, names), "note": body.note})
    return _out(ctx, r, names)


__all__: List[str] = ["router"]
