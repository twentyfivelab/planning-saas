"""Synchronisation en temps réel entre managers : après chaque transaction validée qui écrit dans le journal d'audit
(toute modification métier y passe : affectations, fiches, budgets, générations…), un message est publié sur Redis ;
les navigateurs abonnés au flux `/events` (Server-Sent Events) se rechargent immédiatement."""
import json
import logging
from datetime import datetime, timezone

from sqlalchemy import event

from .config import settings
from .db import SessionLocal
from . import models as m

log = logging.getLogger(__name__)
_client = None


def channel(tenant_id) -> str:
    return f"planning:changes:{tenant_id}"


def _redis():
    global _client
    if _client is None:
        from redis import Redis
        _client = Redis.from_url(settings.redis_url, socket_timeout=1, socket_connect_timeout=1)
    return _client


def publish(tenant_id, actions, origin=None) -> None:
    """Jamais bloquant pour l'écriture : en cas d'indisponibilité de Redis, les clients se resynchronisent par interrogation."""
    try:
        _redis().publish(channel(tenant_id), json.dumps({"at": datetime.now(timezone.utc).isoformat(), "actions": sorted(actions)[:20], "origin": origin}))
    except Exception as exc:  # noqa: BLE001
        log.warning("publication temps réel impossible : %s", type(exc).__name__)


@event.listens_for(SessionLocal, "after_flush")
def _collect(session, _ctx):
    for obj in session.new:
        if isinstance(obj, m.AuditLog) and obj.tenant_id is not None:
            session.info.setdefault("rt_changes", {}).setdefault(str(obj.tenant_id), set()).add(obj.action)


@event.listens_for(SessionLocal, "after_commit")
def _publish(session):
    changes = session.info.pop("rt_changes", None)
    for tid, actions in (changes or {}).items():
        publish(tid, actions, session.info.get("rt_origin"))  # l'onglet auteur, déjà rechargé, peut ignorer sa propre annonce


@event.listens_for(SessionLocal, "after_rollback")
def _drop(session):
    session.info.pop("rt_changes", None)  # transaction annulée : rien à annoncer
