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
    for r in ctx.db.scalars(select(m.OptimizationRun).where(m.OptimizationRun.period_id == p.id, m.OptimizationRun.status.in_(("en_attente", "en_cours")))):
        r.cancel_requested = True  # calcul en file ou en cours : annulé (et, s'il se termine quand même, rien n'est écrit)
    from .. import replacements as R
    for req in ctx.db.scalars(select(m.ReplacementRequest).where(m.ReplacementRequest.period_id == p.id, m.ReplacementRequest.status == "open")):
        # proposition de remplacement en cours : plus valable, le collaborateur sollicité est prévenu (jamais un « Accepter » sur un planning supprimé)
        R.invalidate(ctx.db, req, "Le planning de ce mois a été supprimé.", ctx.user.id)
    # 4) trace, dans la même transaction : identité de la personne (nom et identifiant interne), planning, nombre d'affectations
    audit(ctx, "period.deleted", "period", p.id, {"period_id": str(p.id), "period": p.name, "month": p.start_date.strftime("%Y-%m"), "label": pv["label"],
                                                   "status": pv["status"], "status_label": pv["status_label"],
                                                   "by": {"id": str(ctx.user.id), "name": ctx.user.name}, "assignments": pv["assignments"],
                                                   "locked": pv["locked"], "shifts": pv["shifts"], "versions": pv["versions"], "runs": pv["runs"]})
    ctx.db.flush()
    return {"message": f"Le planning de {pv['label']} a été supprimé avec succès.", "period_id": str(p.id), "assignments": pv["assignments"],
            "deleted_at": now.isoformat(), "deleted_by": {"id": str(ctx.user.id), "name": ctx.user.name}}


# ---- récupération contrôlée d'un planning supprimé (à partir de son archive) ----
# Le planning supprimé, son archive et la trace de la suppression restent INCHANGÉS (protégés en base) : la récupération crée un NOUVEAU
# planning actif pour le même mois, refusée si ce mois a déjà un planning actif. Aucun autre mois n'est lu ni modifié. Mêmes droits et
# même confirmation par mot de passe que la suppression ; le plafond mensuel s'applique (tout ou rien). Rien n'est publié.

def _deleted_period(ctx: Ctx, pid: str) -> m.PlanningPeriod:
    import uuid
    try:
        key = uuid.UUID(str(pid))
    except ValueError:
        raise HTTPException(404, "Introuvable")
    p = ctx.db.get(m.PlanningPeriod, key)
    if p is None:
        raise HTTPException(404, "Introuvable")
    if p.deleted_at is None:
        raise HTTPException(409, detail={"code": "not_deleted", "message": f"Le planning de {_label(p)} n'est pas supprimé : rien à récupérer."})
    return p


def _rebuild(ctx: Ctx, old: m.PlanningPeriod) -> dict:
    """Crée le nouveau planning et y replace les affectations archivées. À appeler dans une transaction (ou un point de sauvegarde)."""
    from datetime import date, time
    from ..limits import guard_monthly_cap, month_minutes
    from planning_solver.timecalc import shift_hours
    from .months import find_period
    blocking = []
    if find_period(ctx, old.start_date, old.end_date) is not None:
        blocking.append(f"Le mois de {_label(old)} a déjà un planning actif : supprimez-le d'abord ou conservez-le. Rien n'a été modifié.")
    archive = (old.deletion_archive or {}).get("assignments") or []
    if not archive:
        blocking.append("L'archive de ce planning ne contient aucune affectation : rien à récupérer.")
    if blocking:
        return {"blocking": blocking}
    new = m.PlanningPeriod(tenant_id=ctx.tenant_id, name=old.name, start_date=old.start_date, end_date=old.end_date,
                           frozen_params=old.frozen_params, frozen_at=old.frozen_at, frozen_source=old.frozen_source,
                           budget_init=old.budget_init or {"legacy": True})  # budgets du mois : déjà rattachés au mois, jamais repréremplis
    ctx.db.add(new)
    ctx.db.flush()
    for row in ctx.db.scalars(select(m.PeriodEmployee).where(m.PeriodEmployee.period_id == old.id)):  # effectif du mois tel qu'il était
        ctx.db.add(m.PeriodEmployee(tenant_id=ctx.tenant_id, period_id=new.id, employee_id=row.employee_id, included=row.included, reason=row.reason))
    for row in ctx.db.scalars(select(m.PeriodBrand).where(m.PeriodBrand.period_id == old.id)):
        ctx.db.add(m.PeriodBrand(tenant_id=ctx.tenant_id, period_id=new.id, brand_code=row.brand_code, active=row.active))
    for row in ctx.db.scalars(select(m.PeriodSite).where(m.PeriodSite.period_id == old.id)):  # sites activés ou non ce mois-là
        ctx.db.add(m.PeriodSite(tenant_id=ctx.tenant_id, period_id=new.id, site_code=row.site_code, active=row.active))
    emps_by_id = {str(e.id): e for e in ctx.db.scalars(select(m.Employee))}
    emps_by_name = {e.name: e for e in emps_by_id.values()}
    months = {(d.year, d.month) for d in (old.start_date, old.end_date)}
    involved = {e.id for x in archive for e in [emps_by_id.get(x.get("employee_id") or "") or emps_by_name.get(x.get("employee"))] if e is not None}
    before = month_minutes(ctx.db, involved, months)
    restored, missing_emp, missing_shift = 0, [], []
    for x in archive:
        e = emps_by_id.get(x.get("employee_id") or "") or emps_by_name.get(x.get("employee"))
        if e is None:  # collaborateur supprimé depuis : jamais remplacé par un autre
            missing_emp.append({"day": x.get("day"), "start": x.get("start"), "end": x.get("end"), "site": x.get("site"), "employee": x.get("employee")})
            continue
        if not x.get("site") or not x.get("day"):
            missing_shift.append(x.get("slot_key"))
            continue
        day, start, end = date.fromisoformat(x["day"]), time.fromisoformat(x["start"]), time.fromisoformat(x["end"])
        h = shift_hours(day, start, end, x.get("break_minutes") or 0)
        sh = m.Shift(tenant_id=ctx.tenant_id, period_id=new.id, slot_key=x["slot_key"], day=day, site_code=x["site"], start_time=start, end_time=end,
                     break_minutes=x.get("break_minutes") or 0, presence_minutes=h.presence_minutes, effective_minutes=h.effective_minutes)
        ctx.db.add(sh)
        ctx.db.flush()
        a = m.Assignment(tenant_id=ctx.tenant_id, period_id=new.id, shift_id=sh.id, employee_id=e.id, source=x.get("source") or "manual", locked=bool(x.get("locked")))
        ctx.db.add(a)
        ctx.db.flush()
        ctx.db.add(m.Break(tenant_id=ctx.tenant_id, assignment_id=a.id, minutes=sh.break_minutes, paid=False))
        for b, mi in (x.get("allocations") or {}).items():
            ctx.db.add(m.BrandAllocation(tenant_id=ctx.tenant_id, assignment_id=a.id, brand_code=b, minutes=mi))
        restored += 1
    ctx.db.flush()
    try:
        guard_monthly_cap(ctx.db, ctx.tenant_id, before, involved, months)
    except HTTPException as exc:  # plafond : récupération refusée en entier (le message nomme les collaborateurs concernés)
        d = exc.detail if isinstance(exc.detail, dict) else {"message": str(exc.detail)}
        return {"blocking": [d.get("message", "Plafond mensuel dépassé.")], "cap_issues": d.get("issues", [])}
    from .. import regularize
    from ..optimize import ensure_frozen
    regularize.resolve(ctx.db, new.id)
    ensure_frozen(ctx.db, new, "manual")
    return {"blocking": [], "period": new, "restored": restored, "archived": len(archive), "missing_employees": missing_emp, "missing_shifts": missing_shift}


def _recovery_view(old: m.PlanningPeriod, r: dict) -> dict:
    counts = (old.deletion_archive or {}).get("counts") or {}
    return {"period_id": str(old.id), "name": old.name, "label": _label(old), "deleted_at": old.deleted_at.isoformat() if old.deleted_at else None,
            "deleted_by_name": old.deleted_by_name, "archived": len((old.deletion_archive or {}).get("assignments") or []), "archived_locked": counts.get("locked", 0),
            "blocking": r["blocking"], "cap_issues": r.get("cap_issues", []), "can_recover": not r["blocking"],
            "restorable": r.get("restored", 0), "missing_employees": r.get("missing_employees", []), "missing_shifts": len(r.get("missing_shifts", []))}


@router.get("/periods/{pid}/recovery-preview")
def recovery_preview(pid: str, ctx: Ctx = Depends(require("planning.delete"))):
    """Essai à blanc : la récupération est calculée dans un point de sauvegarde puis annulée. Rien n'est modifié."""
    old = _deleted_period(ctx, pid)
    sp = ctx.db.begin_nested()
    try:
        r = _rebuild(ctx, old)
        view = _recovery_view(old, r)
    finally:
        sp.rollback()
    return view


@router.post("/periods/{pid}/recover")
def recover_period(pid: str, body: DeleteIn, ctx: Ctx = Depends(require("planning.delete"))):
    if _failures(ctx) >= MAX_FAILURES:
        raise HTTPException(429, detail={"code": "too_many_attempts", "message": "Trop de mots de passe incorrects : réessayez dans quelques minutes. Rien n'a été modifié."},
                            headers={"Retry-After": str(WINDOW_S)})
    if not ctx.user.password_hash:
        raise HTTPException(409, detail={"code": "reauth_required", "message": "Ce compte se connecte par un fournisseur externe : reconnectez-vous auprès de lui pour confirmer. Rien n'a été modifié."})
    if not verify_password(body.password, ctx.user.password_hash):
        _record_failure(ctx)
        raise HTTPException(403, detail={"code": "wrong_password", "message": "Mot de passe incorrect. Rien n'a été modifié."})
    _clear_failures(ctx)
    old = _deleted_period(ctx, pid)
    # un seul planning actif par mois : verrou consultatif sur (entreprise, mois) contre deux récupérations simultanées
    from sqlalchemy import text
    ctx.db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"recover:{ctx.tenant_id}:{old.start_date.isoformat()}"})
    sp = ctx.db.begin_nested()  # tout ou rien : un refus (plafond, mois occupé) annule ce qui a été préparé
    r = _rebuild(ctx, old)
    if r["blocking"]:
        sp.rollback()
        raise HTTPException(409, detail={"code": "blocked", "message": " ".join(r["blocking"]), "cap_issues": r.get("cap_issues", [])})
    sp.commit()
    new = r["period"]
    audit(ctx, "period.recovered", "period", new.id, {"period_id": str(new.id), "period": new.name, "month": new.start_date.strftime("%Y-%m"), "label": _label(new),
                                                       "from_period_id": str(old.id), "deleted_at": old.deleted_at.isoformat() if old.deleted_at else None,
                                                       "deleted_by_name": old.deleted_by_name, "by": {"id": str(ctx.user.id), "name": ctx.user.name},
                                                       "restored": r["restored"], "archived": r["archived"], "missing_employees": len(r["missing_employees"]),
                                                       "missing_shifts": len(r["missing_shifts"])})
    ctx.db.flush()
    return {"message": f"Le planning de {_label(new)} a été récupéré : {r['restored']} affectation(s) sur {r['archived']} replacée(s). Il n'est pas publié.",
            "period_id": str(new.id), "restored": r["restored"], "archived": r["archived"], "missing_employees": r["missing_employees"]}


__all__: Optional[list] = ["router"]
