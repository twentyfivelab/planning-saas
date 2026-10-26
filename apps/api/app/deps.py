import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterator

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from . import models as m
from .db import SessionLocal, tenant_session
from .rbac import has_permission
from .security import csrf_ok, token_hash

COOKIE = "session"


@dataclass
class Ctx:
    db: Session
    user: m.User
    tenant_id: uuid.UUID
    csrf: str


def _session_row(request: Request):
    tok = request.cookies.get(COOKIE)
    if not tok:
        raise HTTPException(401, "Non authentifié")
    with SessionLocal() as s:  # table sessions : accès par hash de jeton uniquement
        row = s.get(m.Session_, token_hash(tok))
        if row is None or row.expires_at < datetime.now(timezone.utc):
            raise HTTPException(401, "Session expirée")
        return row


def get_ctx(request: Request) -> Iterator[Ctx]:
    row = _session_row(request)
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        if not csrf_ok(request.headers.get("x-csrf-token", ""), row.csrf_token):
            raise HTTPException(403, "Jeton CSRF invalide")
    with tenant_session(str(row.tenant_id)) as db:
        user = db.get(m.User, row.user_id)
        if user is None or not user.is_active or user.tenant_id != row.tenant_id:
            raise HTTPException(401, "Compte inactif")
        yield Ctx(db, user, row.tenant_id, row.csrf_token)


def require(perm: str):
    def dep(ctx: Ctx = Depends(get_ctx)) -> Ctx:
        if not has_permission(ctx.user.role, perm):
            raise HTTPException(403, f"Permission requise : {perm}")
        return ctx
    return dep


def audit(ctx: Ctx, action: str, entity: str = None, entity_id=None, detail: dict = None) -> None:
    ctx.db.add(m.AuditLog(tenant_id=ctx.tenant_id, user_id=ctx.user.id, action=action, entity=entity,
                          entity_id=str(entity_id) if entity_id else None, detail=detail or {}))


def get_or_404(ctx: Ctx, model, id_):
    """RLS garantit qu'un id d'un autre tenant est invisible -> 404 (pas 403, pas de fuite d'existence)."""
    try:
        key = uuid.UUID(str(id_))
    except ValueError:
        raise HTTPException(404, "Introuvable")
    obj = ctx.db.get(model, key)
    if obj is None:
        raise HTTPException(404, "Introuvable")
    return obj
