"""Suppression d'un planning généré : aperçu, confirmation par le mot de passe du compte connecté, suppression LOGIQUE et trace.

- Droit dédié « planning.delete » (propriétaire, administrateur), vérifié côté serveur ; l'entreprise est garantie par la RLS.
- Mot de passe vérifié côté serveur, jamais stocké ni journalisé ; échecs limités (5 par quart d'heure et par compte) ; un compte sans
  mot de passe local (connexion externe) doit se réauthentifier par son fournisseur : la suppression est alors refusée avec ce motif.
- Une seule transaction : archive des affectations dans le planning, retrait des affectations et shifts des vues actives, marquage du
  planning comme supprimé et entrée « Suppression d'un planning » au journal. Tout ou rien.
- Rien d'autre n'est modifié : autres mois, collaborateurs, paramètres, versions (conservées, masquées), calculs (conservés).
- Le planning supprimé et l'entrée du journal sont protégés en base (déclencheurs de la migration 0015)."""
import time as _time
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from .. import models as m
from ..config import settings
from ..deps import Ctx, audit, require
from ..security import verify_password
from ..period_state import statuses
from .months import MONTHS_FR

router = APIRouter(tags=["suppression d'un planning"])

MAX_FAILURES, WINDOW_S = 5, 15 * 60
_mem_failures: dict = {}


def _failures_key(ctx: Ctx) -> str:
    return f"pwcheck:{ctx.tenant_id}:{ctx.user.id}"


def _failures(ctx: Ctx) -> int:
    """Échecs récents de vérification du mot de passe pour ce compte (Redis, partagé entre processus ; mémoire en secours)."""
    key = _failures_key(ctx)
    try:
        from redis import Redis
        v = Redis.from_url(settings.redis_url, socket_timeout=1).get(key)
        return int(v or 0)
    except Exception:  # noqa: BLE001 — Redis indisponible : compteur en mémoire de ce processus
        now = _time.time()
        hits = [t for t in _mem_failures.get(key, []) if now - t < WINDOW_S]
        _mem_failures[key] = hits
        return len(hits)


def _record_failure(ctx: Ctx) -> None:
    key = _failures_key(ctx)
    try:
        from redis import Redis
        r = Redis.from_url(settings.redis_url, socket_timeout=1)
        n = r.incr(key)
        if n == 1:
            r.expire(key, WINDOW_S)
    except Exception:  # noqa: BLE001
        _mem_failures.setdefault(key, []).append(_time.time())


def _clear_failures(ctx: Ctx) -> None:
    key = _failures_key(ctx)
    try:
        from redis import Redis
        Redis.from_url(settings.redis_url, socket_timeout=1).delete(key)
    except Exception:  # noqa: BLE001
        _mem_failures.pop(key, None)


def _active_period(ctx: Ctx, pid: str, lock: bool = False) -> m.PlanningPeriod:
    import uuid
    try:
        key = uuid.UUID(str(pid))
    except ValueError:
        raise HTTPException(404, "Introuvable")
    q = select(m.PlanningPeriod).where(m.PlanningPeriod.id == key)
    p = ctx.db.execute(q.with_for_update() if lock else q).scalar_one_or_none()
    if p is None:
        raise HTTPException(404, "Introuvable")
    if p.deleted_at is not None:
        raise HTTPException(409, detail={"code": "already_deleted", "message": f"Le planning de {_label(p)} a déjà été supprimé."})
    return p


def _label(p: m.PlanningPeriod) -> str:
    return f"{MONTHS_FR[p.start_date.month - 1].lower()} {p.start_date.year}"


def _preview(ctx: Ctx, p: m.PlanningPeriod) -> dict:
    count = lambda model, *cond: ctx.db.scalar(select(func.count()).select_from(model).where(*cond)) or 0  # noqa: E731
    versions = list(ctx.db.scalars(select(m.ScheduleVersion).where(m.ScheduleVersion.period_id == p.id)))
    out = {
        "period_id": str(p.id), "name": p.name, "label": _label(p),
        "assignments": count(m.Assignment, m.Assignment.period_id == p.id),
        "locked": count(m.Assignment, m.Assignment.period_id == p.id, m.Assignment.locked.is_(True)),
        "shifts": count(m.Shift, m.Shift.period_id == p.id),
        "versions": {"total": len(versions), "published": sum(1 for v in versions if v.state == "published"),
                     "validated": sum(1 for v in versions if v.state == "validated")},
        "runs": count(m.OptimizationRun, m.OptimizationRun.period_id == p.id),
        "time_entries": count(m.TimeEntry, m.TimeEntry.period_id == p.id),
        "reminders": count(m.Regularization, m.Regularization.period_id == p.id, m.Regularization.resolved_at.is_(None)),
    }
    st = statuses(ctx.db, [p])[p.id]
    out["status"], out["status_label"] = st["status"], st["status_label"]
    blocking = []
    if out["time_entries"]:
        blocking.append(f"{out['time_entries']} saisie(s) d'heures réelles sont rattachées à ce planning : il ne peut pas être supprimé (il peut être archivé).")
    out["blocking"] = blocking
    out["can_delete"] = not blocking  # brouillon jamais généré compris : même confirmation, même suppression logique, même trace
    return out


@router.get("/periods/{pid}/deletion-preview")
def deletion_preview(pid: str, ctx: Ctx = Depends(require("planning.delete"))):
    """Ce qui sera retiré des vues actives, et ce qui empêcherait la suppression. Ne modifie rien."""
    return _preview(ctx, _active_period(ctx, pid))


class DeleteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: str = Field(min_length=1, max_length=256)


@router.post("/periods/{pid}/delete")
def delete_period(pid: str, body: DeleteIn, ctx: Ctx = Depends(require("planning.delete"))):
    # 1) tentatives limitées, puis vérification du mot de passe du compte CONNECTÉ (jamais stocké, jamais journalisé)
    if _failures(ctx) >= MAX_FAILURES:
        raise HTTPException(429, detail={"code": "too_many_attempts", "message": "Trop de mots de passe incorrects : réessayez dans quelques minutes. Le planning n'a pas été modifié."},
                            headers={"Retry-After": str(WINDOW_S)})
    if not ctx.user.password_hash:
        raise HTTPException(409, detail={"code": "reauth_required", "message": "Ce compte se connecte par un fournisseur externe : reconnectez-vous auprès de lui pour confirmer la suppression. Le planning n'a pas été modifié."})
    if not verify_password(body.password, ctx.user.password_hash):
        _record_failure(ctx)
        raise HTTPException(403, detail={"code": "wrong_password", "message": "Mot de passe incorrect. Le planning n'a pas été modifié."})
    _clear_failures(ctx)
    # 2) planning verrouillé pendant l'opération : une double soumission trouve le planning déjà supprimé
    p = _active_period(ctx, pid, lock=True)
    pv = _preview(ctx, p)
    if not pv["can_delete"]:
        raise HTTPException(409, detail={"code": "blocked", "message": " ".join(pv["blocking"])})
    from ..versioning import snapshot_of
    now = datetime.now(timezone.utc)
    archive = {"assignments": snapshot_of(ctx.db, p.id), "counts": {k: pv[k] for k in ("assignments", "locked", "shifts", "versions", "runs", "reminders")},
               "deleted_at": now.isoformat()}
    # 3) retrait des vues actives (les versions, calculs, effectif et paramètres du mois restent en base, masqués avec le planning)
    for model in (m.Regularization,):
        for row in ctx.db.scalars(select(model).where(model.period_id == p.id)):
            ctx.db.delete(row)
    for row in ctx.db.scalars(select(m.Assignment).where(m.Assignment.period_id == p.id)):
        ctx.db.delete(row)  # imputations, pauses et verrous suivent (suppression en cascade)
    ctx.db.flush()
    for row in ctx.db.scalars(select(m.Shift).where(m.Shift.period_id == p.id)):
        ctx.db.delete(row)
    ctx.db.flush()
    p.deleted_at, p.deleted_by, p.deleted_by_name, p.deletion_archive, p.wizard_step = now, ctx.user.id, ctx.user.name, archive, None
    # 4) trace, dans la même transaction : identité de la personne (nom et identifiant interne), planning, nombre d'affectations
    audit(ctx, "period.deleted", "period", p.id, {"period_id": str(p.id), "period": p.name, "month": p.start_date.strftime("%Y-%m"), "label": pv["label"],
                                                   "status": pv["status"], "status_label": pv["status_label"],
                                                   "by": {"id": str(ctx.user.id), "name": ctx.user.name}, "assignments": pv["assignments"],
                                                   "locked": pv["locked"], "shifts": pv["shifts"], "versions": pv["versions"], "runs": pv["runs"]})
    ctx.db.flush()
    return {"message": f"Le planning de {pv['label']} a été supprimé avec succès.", "period_id": str(p.id), "assignments": pv["assignments"],
            "deleted_at": now.isoformat(), "deleted_by": {"id": str(ctx.user.id), "name": ctx.user.name}}


__all__: Optional[list] = ["router"]
