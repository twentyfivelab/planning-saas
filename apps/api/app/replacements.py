"""Propositions de remplacement envoyées aux collaborateurs.

Règles (voir docs/suivi-wfm.md) :
- Le manager lance la demande depuis les remplaçants classés : les candidats compatibles, dans l'ordre du classement, à partir de
  celui qu'il a choisi. Une seule demande ouverte et une seule proposition en attente par shift (index uniques en base).
- L'affectation actuelle reste en place pendant toute l'attente ; un refus, une expiration, une annulation ou une invalidation ne
  retire jamais le titulaire : le shift n'est jamais laissé vacant par ce circuit.
- Refus ou expiration : le candidat suivant est sollicité automatiquement (s'il est toujours compatible et a un compte). Échéance =
  maintenant + délai de réponse, jamais après le début du shift.
- Acceptation : proposition, demande, shift, affectation et collaborateur verrouillés ; empreinte du shift et du titulaire comparée à
  celle du lancement ; toutes les contraintes actives revérifiées (aucune dérogation possible par le collaborateur) ; transfert en UNE
  transaction. Deux acceptations simultanées ne peuvent pas créer de double affectation.
- Shift modifié, supprimé ou déjà remplacé pendant l'attente : la demande devient caduque (détecté à chaque modification enregistrée,
  et de nouveau à l'acceptation) ; le collaborateur et le manager sont prévenus.
- Chaque étape est journalisée (auteur, date) ; notifications internes, une par événement, jamais répétées. Rien n'est publié :
  le planning publié est mis à jour par la publication habituelle."""
import logging
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import event, select

from . import models as m
from .config import settings

log = logging.getLogger(__name__)
MIN_LEAD = timedelta(minutes=5)  # en deçà du début du shift, plus de proposition
DAYS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
MONTHS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre")
STATUS_LABEL = {"pending": "En attente de réponse", "accepted": "Acceptée", "refused": "Refusée", "expired": "Expirée", "cancelled": "Annulée",
                "invalidated": "Plus valable", "open": "En cours", "filled": "Remplacement effectué", "exhausted": "Aucun remplaçant n'a accepté"}


def now() -> datetime:
    return datetime.now(timezone.utc)


def tz(db, tenant_id) -> ZoneInfo:
    t = db.get(m.Tenant, tenant_id)
    try:
        return ZoneInfo(t.timezone if t and t.timezone else "Europe/Zurich")
    except Exception:  # noqa: BLE001
        return ZoneInfo("Europe/Zurich")


def shift_start(db, sh: m.Shift) -> datetime:
    return datetime.combine(sh.day, sh.start_time, tz(db, sh.tenant_id)).astimezone(timezone.utc)


def when(db, tenant_id, dt: datetime) -> str:
    x = dt.astimezone(tz(db, tenant_id))
    return f"{DAYS[x.weekday()]} {x.day} {MONTHS[x.month - 1]} à {x:%H:%M}"


def _brands(db, sh: m.Shift) -> list:
    return sorted(set(db.scalars(select(m.BrandAllocation.brand_code).join(m.Assignment, m.Assignment.id == m.BrandAllocation.assignment_id)
                                 .where(m.Assignment.shift_id == sh.id))))


def fingerprint(db, sh: m.Shift) -> dict:
    """Ce qui ne doit pas avoir changé pour qu'une proposition reste applicable : horaires, site, pause, titulaire, imputations."""
    a = db.scalar(select(m.Assignment).where(m.Assignment.shift_id == sh.id))
    allocs = sorted((b.brand_code, b.minutes) for b in db.scalars(select(m.BrandAllocation).where(m.BrandAllocation.assignment_id == a.id))) if a else []
    return {"day": sh.day.isoformat(), "start": sh.start_time.isoformat(), "end": sh.end_time.isoformat(), "site": sh.site_code,
            "break": sh.break_minutes, "assignment_id": str(a.id) if a else None, "employee_id": str(a.employee_id) if a else None,
            "allocations": [list(x) for x in allocs]}


def label(db, sh: m.Shift) -> str:
    site = db.scalar(select(m.Site.name).where(m.Site.code == sh.site_code)) or sh.site_code
    brands = {b.code: b.name for b in db.scalars(select(m.Brand))}
    names = " / ".join(brands.get(b, b) for b in _brands(db, sh))
    return f"{DAYS[sh.day.weekday()]} {sh.day.day} {MONTHS[sh.day.month - 1]} {sh.day.year}, {sh.start_time:%H:%M}–{sh.end_time:%H:%M}, {site}" + (f", {names}" if names else "")


def account(db, employee_id) -> Optional[m.User]:
    return db.scalar(select(m.User).where(m.User.employee_id == employee_id, m.User.is_active.is_(True)).limit(1))


def _audit(db, req: m.ReplacementRequest, action: str, actor, **detail) -> None:
    sh = db.get(m.Shift, req.shift_id) if req.shift_id else None
    base = {"period_id": str(req.period_id), "request_id": str(req.id), "shift": req.shift_label}
    if sh is not None:
        from .history import shift_context
        base.update(shift_context(db, sh))
    db.add(m.AuditLog(tenant_id=req.tenant_id, user_id=actor, action=action, entity="replacement", entity_id=str(req.id), detail={**base, **detail}))


def _notify(db, user_id, kind: str, title: str, body: str, payload: dict) -> None:
    if user_id is None:
        return
    u = db.get(m.User, user_id)
    if u is not None and u.is_active:
        db.add(m.Notification(tenant_id=u.tenant_id, user_id=u.id, kind=kind, title=title, body=body, payload=payload))


def _ctx(db):
    return SimpleNamespace(db=db)


def blocking_issues(db, p: m.PlanningPeriod, e: m.Employee, sh: m.Shift) -> list:
    """Contraintes actives que l'acceptation ne respecterait pas. Le collaborateur ne peut déroger à rien : toute alerte autre qu'une
    simple préférence rend la proposition inapplicable."""
    from .routers.manual_shifts import _issues
    current = db.scalar(select(m.Assignment).where(m.Assignment.shift_id == sh.id))
    return [i for i in _issues(_ctx(db), p, e, sh, current) if i["level"] in ("blocking", "override")]


def _schedule_expiry(db, tenant_id, offer_id, at: datetime) -> None:
    if settings.opt_execution == "inline":  # tests : expiration vérifiée à la lecture (même règle)
        return

    def go(_s):
        try:
            from redis import Redis
            from rq import Queue
            Queue("optimization", connection=Redis.from_url(settings.redis_url)).enqueue_at(at, "app.replacements.expire_job", str(tenant_id), str(offer_id))
        except Exception as exc:  # noqa: BLE001 — l'expiration reste appliquée à la prochaine lecture
            log.warning("planification de l'échéance impossible : %s", type(exc).__name__)
    event.listen(db, "after_commit", go, once=True)


def offer_next(db, req: m.ReplacementRequest, actor=None, after_rank: int = -1) -> Optional[m.ReplacementOffer]:
    """Sollicite le prochain candidat valable (compte actif, toujours compatible, assez de temps avant le shift). Sinon : demande épuisée,
    le titulaire actuel reste affecté."""
    sh = db.get(m.Shift, req.shift_id) if req.shift_id else None
    p = db.get(m.PlanningPeriod, req.period_id)
    if sh is None:
        return None
    start = shift_start(db, sh)
    for rank, eid in enumerate(req.candidates or []):
        if rank <= after_rank:
            continue
        if start - now() < MIN_LEAD:
            break
        e = db.get(m.Employee, eid)
        if e is None or not e.active or e.deleted_at is not None:
            _audit(db, req, "replacement.skipped", actor, employee=None, rank=rank, reason="Collaborateur inactif ou supprimé")
            continue
        u = account(db, e.id)
        if u is None:
            _audit(db, req, "replacement.skipped", actor, employee={"id": str(e.id), "name": e.name}, rank=rank, reason="Aucun compte relié à sa fiche")
            continue
        issues = blocking_issues(db, p, e, sh)
        if issues:
            _audit(db, req, "replacement.skipped", actor, employee={"id": str(e.id), "name": e.name}, rank=rank, reason=issues[0]["message"])
            continue
        deadline = min(now() + timedelta(minutes=req.response_minutes), start)
        o = m.ReplacementOffer(tenant_id=req.tenant_id, request_id=req.id, shift_id=sh.id, employee_id=e.id, rank=rank, status="pending", deadline_at=deadline)
        db.add(o)
        db.flush()
        _audit(db, req, "replacement.offered", actor, employee={"id": str(e.id), "name": e.name}, rank=rank, deadline=deadline.isoformat(),
               deadline_label=when(db, req.tenant_id, deadline))
        _notify(db, u.id, "replacement_offer", "Proposition de remplacement",
                f"Pouvez-vous reprendre ce shift : {req.shift_label} ? Réponse attendue avant le {when(db, req.tenant_id, deadline)}.",
                {"offer_id": str(o.id), "request_id": str(req.id), "deadline": deadline.isoformat()})
        _schedule_expiry(db, req.tenant_id, o.id, deadline)
        return o
    req.status, req.closed_at = "exhausted", now()
    req.closed_reason = "Aucun autre candidat compatible n'a pu être sollicité" if start - now() >= MIN_LEAD else "Le shift commence bientôt : plus de proposition possible"
    holder = (req.fingerprint or {}).get("employee_id")
    hname = (db.get(m.Employee, holder).name if holder and db.get(m.Employee, holder) else None)
    _audit(db, req, "replacement.exhausted", actor, reason=req.closed_reason, holder=hname)
    _notify(db, req.created_by, "replacement_update", "Remplacement non trouvé",
            f"{req.closed_reason} pour le shift {req.shift_label}." + (f" {hname} reste affecté·e." if hname else ""),
            {"request_id": str(req.id), "period_id": str(req.period_id), "month": p.start_date.strftime("%Y-%m") if p else None})
    return None


def stale_reason(db, req: m.ReplacementRequest) -> Optional[str]:
    """None si la demande est toujours applicable ; sinon l'explication (shift supprimé, déjà remplacé, modifié, planning archivé…)."""
    p = db.get(m.PlanningPeriod, req.period_id)
    if p is None or p.deleted_at is not None:
        return "Le planning de ce mois a été supprimé."
    if p.archived_at is not None:
        return "Le planning de ce mois a été archivé : il n'est plus modifiable."
    sh = db.get(m.Shift, req.shift_id) if req.shift_id else None
    if sh is None:
        return "Le shift a été supprimé du planning."
    fp, cur = req.fingerprint or {}, fingerprint(db, sh)
    if cur["assignment_id"] is None and fp.get("employee_id"):
        return "Le shift n'a plus de titulaire : il a été retiré entre-temps."
    if cur["employee_id"] != fp.get("employee_id"):
        who = db.get(m.Employee, cur["employee_id"])
        return f"Le shift a déjà été attribué à {who.name if who else 'un autre collaborateur'}."
    if any(cur[k] != fp.get(k) for k in ("day", "start", "end", "site", "break")):
        return "Les horaires, la pause ou le site du shift ont été modifiés."
    if cur["allocations"] != fp.get("allocations") or cur["assignment_id"] != fp.get("assignment_id"):
        return "L'affectation du shift a été modifiée (marques ou affectation recréée)."
    return None


def invalidate(db, req: m.ReplacementRequest, reason: str, actor=None) -> None:
    pending = db.scalar(select(m.ReplacementOffer).where(m.ReplacementOffer.request_id == req.id, m.ReplacementOffer.status == "pending"))
    req.status, req.closed_at, req.closed_reason = "invalidated", now(), reason
    p = db.get(m.PlanningPeriod, req.period_id)
    if pending is not None:
        pending.status, pending.responded_at, pending.reason = "invalidated", now(), reason
        e = db.get(m.Employee, pending.employee_id)
        u = account(db, pending.employee_id)
        _notify(db, u.id if u else None, "replacement_cancelled", "Proposition de remplacement plus valable",
                f"La proposition pour le shift {req.shift_label} ne peut plus être acceptée : {reason} Vous n'avez rien à faire.",
                {"offer_id": str(pending.id), "request_id": str(req.id)})
        _audit(db, req, "replacement.invalidated", actor, reason=reason, employee={"id": str(e.id), "name": e.name} if e else None)
    else:
        _audit(db, req, "replacement.invalidated", actor, reason=reason)
    _notify(db, req.created_by, "replacement_update", "Proposition de remplacement caduque",
            f"La demande de remplacement pour le shift {req.shift_label} a été arrêtée : {reason} Aucun transfert n'a été fait par la proposition.",
            {"request_id": str(req.id), "period_id": str(req.period_id), "month": p.start_date.strftime("%Y-%m") if p else None})


def expire_due(db) -> int:
    """Propositions arrivées à échéance : expirées, puis candidat suivant. Appelé à la lecture et par la tâche planifiée."""
    n = 0
    due = list(db.execute(select(m.ReplacementOffer.id, m.ReplacementOffer.shift_id).where(m.ReplacementOffer.status == "pending",
                                                                                         m.ReplacementOffer.deadline_at <= now())).all())
    for oid, sid in due:
        # même ordre de verrouillage que toute modification du shift ; occupé par une autre opération : traité à la lecture suivante
        if sid is not None and db.execute(select(m.Shift.id).where(m.Shift.id == sid).with_for_update(skip_locked=True)).scalar_one_or_none() is None:
            continue
        o = db.execute(select(m.ReplacementOffer).where(m.ReplacementOffer.id == oid, m.ReplacementOffer.status == "pending")
                       .with_for_update(skip_locked=True).execution_options(populate_existing=True)).scalar_one_or_none()
        if o is None:
            continue
        req = db.get(m.ReplacementRequest, o.request_id)
        o.status, o.responded_at = "expired", now()
        e = db.get(m.Employee, o.employee_id)
        _audit(db, req, "replacement.expired", None, employee={"id": str(e.id), "name": e.name} if e else None, rank=o.rank)
        db.flush()
        if req.status == "open":
            reason = stale_reason(db, req)
            if reason:
                invalidate(db, req, reason)
            else:
                offer_next(db, req, None, o.rank)
        n += 1
    return n


def expire_job(tenant_id: str, offer_id: str) -> None:
    """Tâche planifiée à l'échéance d'une proposition (file « optimization », ordonnanceur RQ)."""
    from .db import tenant_session
    with tenant_session(tenant_id) as db:
        expire_due(db)


# ---- caducité détectée à chaque modification enregistrée (manuelle, génération, restauration, suppression…) ----
WATCHED = (m.Shift, m.Assignment, m.BrandAllocation, m.PlanningPeriod)
FLAG = "replacement_dirty"


def mark(session) -> None:
    if session.info.get(FLAG):
        return
    for obj in (*session.new, *session.dirty, *session.deleted):
        if isinstance(obj, WATCHED):
            session.info[FLAG] = True
            return


def evaluate(session) -> None:
    if not session.info.pop(FLAG, False):
        return
    rows = list(session.scalars(select(m.ReplacementRequest).where(m.ReplacementRequest.status == "open")))
    for req in rows:
        reason = stale_reason(session, req)
        if reason:
            invalidate(session, req, reason)
    if rows:
        session.flush()
    session.info.pop(FLAG, None)
