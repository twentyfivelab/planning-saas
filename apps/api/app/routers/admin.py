import uuid
from typing import List, Optional

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
    employee_id: Optional[uuid.UUID] = None  # fiche collaborateur liée au compte (planning publié, notifications, aucune auto-approbation)
    scope_brands: Optional[List[str]] = Field(None, max_length=500)  # périmètre d'un responsable de marque


def _view(u: m.User) -> dict:
    return {"id": str(u.id), "email": u.email, "name": u.name, "role": u.role, "is_active": u.is_active,
            "employee_id": str(u.employee_id) if u.employee_id else None, "scope_brands": (u.scope or {}).get("brands", [])}


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
    if body.employee_id is not None:
        if ctx.db.get(m.Employee, body.employee_id) is None:
            raise HTTPException(422, "Collaborateur inconnu")
        u.employee_id = body.employee_id
    if body.scope_brands is not None:
        known = {b.code for b in ctx.db.scalars(select(m.Brand))}
        if any(b not in known for b in body.scope_brands):
            raise HTTPException(422, "Marque inconnue")
        u.scope = {**(u.scope or {}), "brands": body.scope_brands}
    audit(ctx, "user.update", "user", u.id, {k: str(v) for k, v in body.model_dump(exclude_none=True).items()})
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
                        ("unavailabilities", m.Unavailability), ("partial_absences", m.PartialAbsence), ("leaves", m.LeaveRequest),
                        ("preferences", m.EmployeePreference), ("assignments", m.Assignment), ("skills", m.EmployeeSkill), ("time_entries", m.TimeEntry),
                        ("requests", m.EmployeeRequest)):
        out[name] = [serialize(o) for o in ctx.db.scalars(select(model).where(model.employee_id == e.id))]
    audit(ctx, "gdpr.access_export", "employee", e.id)
    return out


@router.delete("/data-subject/{employee_id}", status_code=204)
def data_subject_erase(employee_id: str, ctx: Ctx = Depends(require("tenant.manage"))):
    """Droit à l'effacement : anonymise le collaborateur, conserve les agrégats de planning."""
    e = get_or_404(ctx, m.Employee, employee_id)
    before = e.name
    e.name, e.active = f"Anonymisé {str(e.id)[:8]}", False
    e.first_name, e.last_name = None, None  # identité et coordonnées de la fiche d'ajout
    e.birth_date, e.address_street, e.address_postal_code, e.address_city, e.address_country, e.phone, e.email = (None,) * 7
    for pr in ctx.db.scalars(select(m.PlanningPeriod).where(m.PlanningPeriod.frozen_params.is_not(None))):  # paramètres conservés
        fp = pr.frozen_params or {}
        if e.code in (fp.get("employees") or {}):
            pr.frozen_params = {**fp, "employees": {k: v for k, v in fp["employees"].items() if k != e.code}}
    for model in (m.EmploymentContract, m.Availability, m.Unavailability, m.PartialAbsence, m.LeaveRequest, m.EmployeePreference, m.EmployeeSkill,
                  m.EmployeeRequest):
        for o in ctx.db.scalars(select(model).where(model.employee_id == e.id)):
            ctx.db.delete(o)
    for r in ctx.db.scalars(select(m.RelationshipPreference).where((m.RelationshipPreference.employee_id == e.id) | (m.RelationshipPreference.other_employee_id == e.id))):
        ctx.db.delete(r)
    for rq in ctx.db.scalars(select(m.EmployeeRequest).where(m.EmployeeRequest.colleague_employee_id == e.id)):  # demandes d'un collègue : sans texte libre
        rq.note, rq.decision_note = None, None
    for t in ctx.db.scalars(select(m.TimeEntry).where(m.TimeEntry.employee_id == e.id)):  # les heures restent pour les agrégats, pas les remarques libres
        t.note, t.absence_reason = None, None
    ctx.db.execute(text("SELECT set_config('app.gdpr_erasure', 'on', true)"))  # seule dérogation à l'immuabilité des versions
    for pr in ctx.db.scalars(select(m.PlanningPeriod).where(m.PlanningPeriod.deletion_archive.is_not(None))):  # archive d'un planning supprimé
        arc = pr.deletion_archive or {}
        rows = arc.get("assignments") or []
        if any(r.get("employee_id") == str(e.id) for r in rows):
            pr.deletion_archive = {**arc, "assignments": [{**r, "employee": e.name} if r.get("employee_id") == str(e.id) else r for r in rows]}
    for v in ctx.db.scalars(select(m.ScheduleVersion)):  # le nom ne reste pas dans les copies de planning
        if v.context and any(x.get("id") == e.code for x in v.context.get("employees", [])):
            v.context = {**v.context, "employees": [{**x, "name": e.name} if x.get("id") == e.code else x for x in v.context["employees"]]}
        if any(x.get("employee_id") == str(e.id) or x.get("employee") == before for x in v.snapshot or []):
            v.snapshot = [{**x, "employee": e.name} if x.get("employee_id") == str(e.id) or x.get("employee") == before else x for x in v.snapshot]
    audit(ctx, "gdpr.erasure", "employee", e.id)
