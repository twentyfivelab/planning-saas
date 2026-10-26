import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import text

from .. import models as m
from ..config import settings
from ..db import SessionLocal, tenant_session
from ..deps import COOKIE, Ctx, audit, get_ctx
from ..rbac import ROLES
from ..security import client_ip, expiry, hash_password, new_csrf, new_token, rate_limit, verify_password, token_hash

router = APIRouter(prefix="/auth", tags=["auth"])


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RegisterIn(Strict):
    tenant_name: str = Field(min_length=2, max_length=200)
    name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    password: str = Field(min_length=12, max_length=200)


class LoginIn(Strict):
    email: EmailStr
    password: str = Field(max_length=200)


def _start_session(response: Response, user_id, tenant_id) -> str:
    tok, th = new_token()
    csrf = new_csrf()
    with SessionLocal() as s, s.begin():
        s.add(m.Session_(token_hash=th, user_id=user_id, tenant_id=tenant_id, csrf_token=csrf, expires_at=expiry()))
    response.set_cookie(COOKIE, tok, httponly=True, samesite="lax", secure=settings.session_cookie_secure,
                        max_age=settings.session_ttl_hours * 3600, path="/")
    return csrf


@router.post("/register", status_code=201)
def register(body: RegisterIn, request: Request, response: Response):
    rate_limit(f"register:{client_ip(request)}", 5)
    tid = uuid.uuid4()
    with tenant_session(str(tid)) as db:
        if db.execute(text("select 1 from auth_lookup_user(:e)"), {"e": body.email.lower()}).first():
            raise HTTPException(409, "Compte existant")
        db.add(m.Tenant(id=tid, name=body.tenant_name))
        db.flush()
        db.add(m.Subscription(tenant_id=tid, plan="trial"))
        u = m.User(tenant_id=tid, email=body.email.lower(), name=body.name, role="owner",
                   password_hash=hash_password(body.password))
        db.add(u)
        db.flush()
        db.add(m.AuditLog(tenant_id=tid, user_id=u.id, action="tenant.created", entity="tenant", entity_id=str(tid)))
        uid = u.id
    csrf = _start_session(response, uid, tid)
    return {"tenant_id": str(tid), "user_id": str(uid), "role": "owner", "csrf_token": csrf}


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response):
    email = body.email.lower()
    rate_limit(f"login:{client_ip(request)}:{email}", settings.login_rate_limit)
    with SessionLocal() as s, s.begin():
        row = s.execute(text("select * from auth_lookup_user(:e)"), {"e": email}).first()
    ok = verify_password(body.password, row.password_hash if row else None)
    if not row or not ok or not row.is_active:
        raise HTTPException(401, "Identifiants invalides")  # message identique : pas d'énumération
    csrf = _start_session(response, row.id, row.tenant_id)
    with tenant_session(str(row.tenant_id)) as db:
        db.add(m.AuditLog(tenant_id=row.tenant_id, user_id=row.id, action="auth.login"))
    return {"user_id": str(row.id), "tenant_id": str(row.tenant_id), "role": row.role, "csrf_token": csrf}


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, ctx: Ctx = Depends(get_ctx)):
    tok = request.cookies.get(COOKIE)
    with SessionLocal() as s, s.begin():
        s.execute(text("delete from sessions where token_hash=:h"), {"h": token_hash(tok)})
    response.delete_cookie(COOKIE, path="/")
    audit(ctx, "auth.logout")


@router.get("/me")
def me(ctx: Ctx = Depends(get_ctx)):
    return {"id": str(ctx.user.id), "email": ctx.user.email, "name": ctx.user.name, "role": ctx.user.role,
            "tenant_id": str(ctx.tenant_id), "csrf_token": ctx.csrf,
            "permissions": sorted(ROLES[ctx.user.role][1])}
