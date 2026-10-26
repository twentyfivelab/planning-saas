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
