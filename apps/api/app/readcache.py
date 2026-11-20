"""Cache des LECTURES d'affichage partagées par les managers (mesure à plusieurs managers du 20/11/2026 : chaque modification faisait
recalculer les mêmes vues — conflits, dimanches, compatibilité… — par chaque écran ouvert, et l'API saturait dès 10 managers).

Règles de sûreté :
- clé = entreprise + rôle et périmètre de l'utilisateur + adresse demandée + empreinte de révision (journal d'audit) : toute modification
  métier (elle est toujours journalisée) change l'empreinte, la vue est alors recalculée ;
- durée de vie courte (10 s) : même une écriture non journalisée ne peut jamais laisser une vue périmée plus longtemps ;
- uniquement pour l'AFFICHAGE : les contrôles d'une modification (manuelle, génération, remplacement) ne passent jamais par ce cache ;
- par processus, borné en taille ; résultat recopié à chaque lecture (jamais partagé par référence)."""
import copy
import functools
import json
import threading
import time
from collections import OrderedDict
from typing import Any, Callable

from sqlalchemy import func, select

from . import models as m

TTL_S = 10.0
MAX_ENTRIES = 512
_lock = threading.Lock()
_store: "OrderedDict[tuple, tuple[float, Any]]" = OrderedDict()
stats = {"hits": 0, "misses": 0}


def revision(db) -> str:
    """Empreinte légère de l'état partagé de l'entreprise (journal d'audit, append-only ; index tenant_id, created_at)."""
    n, last = db.execute(select(func.count(), func.max(m.AuditLog.created_at)).select_from(m.AuditLog)).one()
    return f"{n}:{last.isoformat() if last else ''}"


def cached(ctx, key: str, compute: Callable[[], Any]) -> Any:
    k = (str(ctx.tenant_id), ctx.user.role, json.dumps(ctx.user.scope or {}, sort_keys=True, default=str), key, revision(ctx.db))
    now = time.monotonic()
    with _lock:
        hit = _store.get(k)
        if hit is not None and now - hit[0] < TTL_S:
            _store.move_to_end(k)
            stats["hits"] += 1
            return copy.deepcopy(hit[1])
    value = compute()
    with _lock:
        stats["misses"] += 1
        _store[k] = (now, copy.deepcopy(value))
        _store.move_to_end(k)
        while len(_store) > MAX_ENTRIES:
            _store.popitem(last=False)
    return value


def clear() -> None:
    with _lock:
        _store.clear()


def cached_view(name: str):
    """Décorateur d'une route de LECTURE d'affichage. Un appel interne sans `ctx` nommé (exports, résumés) n'utilise jamais le cache."""
    def deco(fn):
        @functools.wraps(fn)
        def inner(*args, **kwargs):
            ctx = kwargs.get("ctx")
            if ctx is None or args:
                return fn(*args, **kwargs)
            key = name + json.dumps({k: str(v) for k, v in kwargs.items() if k != "ctx"}, sort_keys=True)
            return cached(ctx, key, lambda: fn(*args, **kwargs))
        return inner
    return deco
