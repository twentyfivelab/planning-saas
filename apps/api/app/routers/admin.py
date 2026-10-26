import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from .. import models as m
from ..deps import Ctx, audit, get_or_404, require
from ..rbac import ROLES
from ..security import hash_password

router = APIRouter(tags=["administration"])


class UserIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr
    name: str = Field(max_length=200)
    role: str
    password: str = Field(min_length=12, max_length=200)
    employee_id: Optional[uuid.UUID] = None


class UserPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Optional[str] = None
    is_active: Optional[bool] = None


def _view(u: m.User) -> dict:
    return {"id": str(u.id), "email": u.email, "name": u.name, "role": u.role, "is_active": u.is_active}


@router.get("/users")
def users(ctx: Ctx = Depends(require("users.manage"))):
    return [_view(u) for u in ctx.db.scalars(select(m.User).order_by(m.User.created_at))]


@router.post("/users", status_code=201)
def create_user(body: UserIn, ctx: Ctx = Depends(require("users.manage"))):
    if body.role not in ROLES or (body.role == "owner" and ctx.user.role != "owner"):
        raise HTTPException(422, "Rôle invalide ou non autorisé")
    if ctx.db.execute(text("select 1 from auth_lookup_user(:e)"), {"e": body.email.lower()}).first():
        raise HTTPException(409, "E-mail déjà utilisé")
    u = m.User(tenant_id=ctx.tenant_id, email=body.email.lower(), name=body.name, role=body.role,
               password_hash=hash_password(body.password), employee_id=body.employee_id)
    ctx.db.add(u)
    try:
        ctx.db.flush()
    except IntegrityError:
        raise HTTPException(409, "E-mail déjà utilisé")
    audit(ctx, "user.create", "user", u.id, {"role": body.role})
    return _view(u)


@router.patch("/users/{uid}")
def patch_user(uid: str, body: UserPatch, ctx: Ctx = Depends(require("users.manage"))):
    u = get_or_404(ctx, m.User, uid)
    if u.role == "owner" and ctx.user.role != "owner":
        raise HTTPException(403, "Seul un propriétaire peut modifier un propriétaire")
    if body.role is not None:
        if body.role not in ROLES or (body.role == "owner" and ctx.user.role != "owner"):
            raise HTTPException(422, "Rôle invalide ou non autorisé")
        u.role = body.role
    if body.is_active is not None:
        u.is_active = body.is_active
    audit(ctx, "user.update", "user", u.id, body.model_dump(exclude_none=True))
    return _view(u)


@router.get("/audit")
def audit_log(ctx: Ctx = Depends(require("audit.read")), limit: int = 200, action: Optional[str] = None):
    q = select(m.AuditLog).order_by(m.AuditLog.created_at.desc()).limit(min(limit, 1000))
    if action:
        q = q.where(m.AuditLog.action == action)
    return [{"id": str(a.id), "at": a.created_at, "user_id": str(a.user_id) if a.user_id else None,
             "action": a.action, "entity": a.entity, "entity_id": a.entity_id, "detail": a.detail}
            for a in ctx.db.scalars(q)]


@router.get("/tenant")
def tenant(ctx: Ctx = Depends(require("self.read"))):
    t = ctx.db.get(m.Tenant, ctx.tenant_id)
    return {"id": str(t.id), "name": t.name, "country": t.country, "timezone": t.timezone, "locale": t.locale,
            "retention_months": t.retention_months}


@router.get("/data-subject/{employee_id}")
def data_subject_export(employee_id: str, ctx: Ctx = Depends(require("tenant.manage"))):
    """Préparation droit d'accès RGPD/LPD : toutes les données rattachées à un collaborateur."""
    e = get_or_404(ctx, m.Employee, employee_id)
    from .crud import serialize
    out = {"employee": serialize(e)}
    for name, model in (("contracts", m.EmploymentContract), ("availabilities", m.Availability),
                        ("unavailabilities", m.Unavailability), ("leaves", m.LeaveRequest),
                        ("preferences", m.EmployeePreference), ("assignments", m.Assignment)):
        out[name] = [serialize(o) for o in ctx.db.scalars(select(model).where(model.employee_id == e.id))]
    audit(ctx, "gdpr.access_export", "employee", e.id)
    return out


@router.delete("/data-subject/{employee_id}", status_code=204)
def data_subject_erase(employee_id: str, ctx: Ctx = Depends(require("tenant.manage"))):
    """Droit à l'effacement : anonymise le collaborateur, conserve les agrégats de planning."""
    e = get_or_404(ctx, m.Employee, employee_id)
    e.name, e.active = f"Anonymisé {str(e.id)[:8]}", False
    for model in (m.EmploymentContract, m.Availability, m.Unavailability, m.LeaveRequest, m.EmployeePreference):
        for o in ctx.db.scalars(select(model).where(model.employee_id == e.id)):
            ctx.db.delete(o)
    audit(ctx, "gdpr.erasure", "employee", e.id)
