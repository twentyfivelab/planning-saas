import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "apps/api"), str(ROOT / "packages/solver")]
# charge .env local pour les tests d'intégration (Postgres du docker compose)
for line in (ROOT / ".env").read_text().splitlines() if (ROOT / ".env").exists() else []:
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k, v)
os.environ["OPT_EXECUTION"] = "inline"
os.environ["APP_ENV"] = "test"
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://x")

# --- base de test ISOLÉE --------------------------------------------------------------------------------------------------------
# Les tests créent un tenant par scénario. Ils tournaient auparavant sur la base de l'application (d'où des centaines de tenants de
# test accumulés à côté des données réelles). Chaque session crée désormais sa propre base (TEST_DB_NAME, par défaut
# « planning_test_<pid> »), y applique les migrations, puis la supprime à la fin (KEEP_TEST_DB=1 pour la garder et l'examiner).
# La base de l'application n'est jamais ouverte par les tests.
import re as _re
from sqlalchemy import create_engine as _ce, text as _text

_REAL_DB = os.environ["DATABASE_URL"].rsplit("/", 1)[-1]
TEST_DB = os.environ.get("TEST_DB_NAME") or f"planning_test_{os.getpid()}"
if not _re.fullmatch(r"planning_test[a-z0-9_]*", TEST_DB) or TEST_DB == _REAL_DB:
    raise RuntimeError(f"TEST_DB_NAME doit commencer par « planning_test » et différer de la base de l'application ({_REAL_DB}).")
_OWNER = os.environ.get("MIGRATION_DATABASE_URL", "")
_ISOLATED = bool(_OWNER) and not os.environ.get("NO_DB_TESTS")
if _ISOLATED:
    _admin = _ce(_OWNER.rsplit("/", 1)[0] + "/postgres", isolation_level="AUTOCOMMIT")
    with _admin.connect() as _c:
        _c.execute(_text(f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)'))
        _c.execute(_text(f'CREATE DATABASE "{TEST_DB}"'))
    os.environ["DATABASE_URL"] = os.environ["DATABASE_URL"].rsplit("/", 1)[0] + "/" + TEST_DB
    os.environ["MIGRATION_DATABASE_URL"] = _OWNER.rsplit("/", 1)[0] + "/" + TEST_DB
    from alembic import command as _alembic
    from alembic.config import Config as _AlembicConfig
    _cfg = _AlembicConfig(str(ROOT / "apps/api/alembic.ini"))
    _cfg.set_main_option("script_location", str(ROOT / "apps/api/alembic"))
    _alembic.upgrade(_cfg, "head")


def pytest_sessionfinish(session, exitstatus):
    if not _ISOLATED or os.environ.get("KEEP_TEST_DB") == "1":
        return
    from app.db import engine as _engine
    _engine.dispose()
    with _admin.connect() as c:
        c.execute(_text(f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)'))


import pytest
from fastapi.testclient import TestClient

from app.main import app
from app import security

PW = "Correct-Horse-Battery-9"


@pytest.fixture(autouse=True)
def _reset():
    security.reset_rate_limits()


def make_client() -> TestClient:
    return TestClient(app, base_url="http://localhost")


def register(client, name, email):
    r = client.post("/auth/register", json={"tenant_name": name, "name": name, "email": email, "password": PW})
    assert r.status_code == 201, r.text
    client.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    return r.json()


@pytest.fixture
def tenant_a():
    import uuid
    c = make_client()
    info = register(c, "Tenant A", f"a-{uuid.uuid4().hex[:8]}@example.com")
    return c, info


@pytest.fixture
def tenant_b():
    import uuid
    c = make_client()
    info = register(c, "Tenant B", f"b-{uuid.uuid4().hex[:8]}@example.com")
    return c, info
