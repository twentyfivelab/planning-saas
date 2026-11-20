import hashlib
import hmac
import logging
import secrets
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError
from fastapi import HTTPException, Request

from .config import settings

_ph = PasswordHasher()  # Argon2id
_DUMMY = _ph.hash("dummy-password-for-timing")


def hash_password(pw: str) -> str:
    return _ph.hash(pw)


def verify_password(pw: str, h: "str | None") -> bool:
    try:
        return _ph.verify(h or _DUMMY, pw) and h is not None
    except (VerifyMismatchError, InvalidHashError):
        return False


def new_token() -> "tuple[str, str]":
    t = secrets.token_urlsafe(32)
    return t, hashlib.sha256(t.encode()).hexdigest()


def token_hash(t: str) -> str:
    return hashlib.sha256(t.encode()).hexdigest()


def new_csrf() -> str:
    return secrets.token_urlsafe(24)


def csrf_ok(a: str, b: str) -> bool:
    return bool(a) and bool(b) and hmac.compare_digest(a, b)


def expiry() -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=settings.session_ttl_hours)


_hits: "dict[str, list[float]]" = defaultdict(list)
_log = logging.getLogger(__name__)


def _rate_limit_redis(key: str, limit: int, window_s: int) -> bool:
    """Fenêtre glissante partagée par tous les processus de l'API (Redis). Renvoie False si Redis est indisponible."""
    try:
        from .realtime import _redis
        r, k, now = _redis(), f"rl:{key}", time.time()
        p = r.pipeline()
        p.zremrangebyscore(k, 0, now - window_s)
        p.zcard(k)
        count = p.execute()[1]
        if count >= limit:
            raise HTTPException(429, "Trop de tentatives, réessayez plus tard.", headers={"Retry-After": str(window_s)})
        p = r.pipeline()
        p.zadd(k, {f"{now:.6f}:{secrets.token_hex(4)}": now})
        p.expire(k, window_s)
        p.execute()
        return True
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 — jamais de connexion bloquée par une panne de Redis : limitation en mémoire
        _log.warning("limitation des tentatives : Redis indisponible (%s), repli en mémoire", type(exc).__name__)
        return False


def rate_limit(key: str, limit: int, window_s: int = 60) -> None:
    """Limitation des tentatives (fenêtre glissante). Plusieurs processus d'API : Redis (`RATE_LIMIT_BACKEND=redis`), sinon en mémoire."""
    if settings.rate_limit_backend == "redis" and _rate_limit_redis(key, limit, window_s):
        return
    now = time.time()
    h = [t for t in _hits[key] if now - t < window_s]
    if len(h) >= limit:
        _hits[key] = h
        raise HTTPException(429, "Trop de tentatives, réessayez plus tard.", headers={"Retry-After": str(window_s)})
    h.append(now)
    _hits[key] = h


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "?"


def reset_rate_limits() -> None:
    _hits.clear()
    if settings.rate_limit_backend == "redis":
        try:
            from .realtime import _redis
            r = _redis()
            for k in r.scan_iter("rl:*"):
                r.delete(k)
        except Exception:  # noqa: BLE001
            pass
