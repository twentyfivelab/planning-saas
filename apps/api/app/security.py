import hashlib
import hmac
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


def rate_limit(key: str, limit: int, window_s: int = 60) -> None:
    """Fenêtre glissante en mémoire (par processus). En production multi-instances : Redis (voir README)."""
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
