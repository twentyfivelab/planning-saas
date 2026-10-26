import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.db import SessionLocal, tenant_session
from tests.conftest import PW, make_client


def emp(code="E1", name="Alice"):
    return {"code": code, "name": name, "brands": {"X": "priority"}}


def test_unauthenticated_and_csrf():
    c = make_client()
    assert c.get("/employees").status_code == 401
    c2 = make_client()
    r = c2.post("/auth/register", json={"tenant_name": "Tenant T", "name": "n", "email": f"{uuid.uuid4().hex}@example.com",
                                        "password": PW})
    assert r.status_code == 201
    assert c2.post("/employees", json=emp()).status_code == 403  # pas de jeton CSRF
    sc = r.headers["set-cookie"].lower()
    assert "httponly" in sc and "samesite=lax" in sc


def test_login_generic_error_and_rate_limit(tenant_a):
    _, info = tenant_a
    c = make_client()
    r1 = c.post("/auth/login", json={"email": "nobody@example.com", "password": "x" * 12})
    me = c.get("/auth/me")
    assert r1.status_code == 401 and me.status_code == 401
    codes = [c.post("/auth/login", json={"email": "nobody@example.com", "password": "bad"}).status_code
             for _ in range(15)]
    assert 429 in codes


def test_password_is_argon2_and_strict_validation(tenant_a):
    c, info = tenant_a
    with tenant_session(info["tenant_id"]) as db:
        h = db.execute(text("select password_hash from users")).scalar()
    assert h.startswith("$argon2id$") and PW not in h
    assert c.post("/employees", json={**emp(), "evil": 1}).status_code == 422
    assert c.post("/employees", json={**emp(), "allocation_weight": -1}).status_code == 422


def test_tenant_isolation_api(tenant_a, tenant_b):
    a, _ = tenant_a
    b, _ = tenant_b
    eid = a.post("/employees", json=emp()).json()["id"]
    assert [e["id"] for e in a.get("/employees").json()] == [eid]
    assert b.get("/employees").json() == []
    # modification directe de l'id dans la requête
    assert b.put(f"/employees/{eid}", json=emp(name="Pirate")).status_code == 404
    assert b.delete(f"/employees/{eid}").status_code == 404
    assert a.get("/employees").json()[0]["name"] == "Alice"
    # référence croisée entre tenants
    r = b.post("/contracts", json={"employee_id": eid, "monthly_max_minutes": 100})
    assert r.status_code == 422
    assert b.get(f"/data-subject/{eid}").status_code == 404
    pid = a.post("/periods", json={"name": "P", "start_date": "2026-11-01", "end_date": "2026-11-30"}).json()["id"]
    assert b.get(f"/periods/{pid}/schedule").status_code == 404
    assert b.get(f"/periods/{pid}/export.csv").status_code == 404
    assert b.post(f"/periods/{pid}/runs", json={}).status_code == 404


def test_rls_enforced_in_database_even_with_raw_sql(tenant_a, tenant_b):
    a, ia = tenant_a
    b, ib = tenant_b
    a.post("/employees", json=emp("Z9", "Zed"))
    with tenant_session(ib["tenant_id"]) as db:
        assert db.execute(text("select count(*) from employees")).scalar() == 0
        with pytest.raises(DBAPIError):  # écriture dans un autre tenant refusée par la politique
            db.execute(text("insert into brands(id, tenant_id, code, name, active_weekdays) "
                            "values (gen_random_uuid(), :t, 'x', 'x', '[]')"), {"t": ia["tenant_id"]})
    with SessionLocal() as s, s.begin():  # sans app.tenant_id : rien de visible
        assert s.execute(text("select count(*) from employees")).scalar() == 0


def test_audit_log_is_append_only(tenant_a):
    c, info = tenant_a
    c.post("/employees", json=emp())
    with tenant_session(info["tenant_id"]) as db:
        assert db.execute(text("select count(*) from audit_logs")).scalar() >= 2
    with pytest.raises(DBAPIError):
        with tenant_session(info["tenant_id"]) as db:
            db.execute(text("update audit_logs set action='x'"))


def _user(owner, role):
    email = f"{role}-{uuid.uuid4().hex[:6]}@example.com"
    assert owner.post("/users", json={"email": email, "name": role, "role": role, "password": PW}).status_code == 201
    c = make_client()
    r = c.post("/auth/login", json={"email": email, "password": PW})
    assert r.status_code == 200
    c.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    return c


def test_role_permissions(tenant_a):
    owner, _ = tenant_a
    eid = owner.post("/employees", json=emp()).json()["id"]
    auditor, planner, employee, manager, admin = (_user(owner, r) for r in
                                                  ("auditor", "planner", "employee", "manager", "admin"))
    # lecture seule
    assert auditor.get("/employees").status_code == 200
    assert auditor.post("/employees", json=emp("E2")).status_code == 403
    assert auditor.delete(f"/employees/{eid}").status_code == 403
    assert auditor.get("/audit").status_code == 200
    # collaborateur : pas d'accès aux données RH ni à l'administration
    assert employee.get("/employees").status_code == 403
    assert employee.get("/users").status_code == 403
    assert employee.get("/audit").status_code == 403
    assert employee.get("/periods").status_code == 200
    # planificateur : édite, ne publie pas, n'administre pas
    assert planner.post("/employees", json=emp("E3")).status_code == 201
    assert planner.get("/users").status_code == 403
    assert planner.get("/audit").status_code == 403
    # manager : pas de gestion des utilisateurs
    assert manager.get("/users").status_code == 403
    assert manager.get("/audit").status_code == 200
    # admin vs owner
    assert admin.get("/users").status_code == 200
    assert admin.post("/users", json={"email": "x@example.com", "name": "x", "role": "owner",
                                      "password": PW}).status_code == 422
    assert owner.post("/users", json={"email": f"{uuid.uuid4().hex}@example.com", "name": "x", "role": "bogus",
                                      "password": PW}).status_code == 422


def test_exception_requires_reason_and_records_activator(tenant_a):
    c, info = tenant_a
    base = {"kind": "exception", "code": "rest_hours", "params": {"value": 9}, "jurisdiction": "CH"}
    assert c.post("/constraints", json=base).status_code == 422
    r = c.post("/constraints", json={**base, "exception_reason": "convention X art. 3"})
    assert r.status_code == 201 and r.json()["enabled_by"] == info["user_id"]
    assert r.json()["legal_review_status"] == "a_valider"


def test_gdpr_erasure_and_import_preview(tenant_a):
    c, _ = tenant_a
    eid = c.post("/employees", json=emp()).json()["id"]
    assert c.get(f"/data-subject/{eid}").json()["employee"]["name"] == "Alice"
    assert c.delete(f"/data-subject/{eid}").status_code == 204
    assert c.get("/employees").json()[0]["name"].startswith("Anonymisé")
    csv = "code,name,brands,weight,unavailable_weekdays\nA1,Zoé,Ploom:priority,1.2,1;3\nA1,Dup,,1,\nB2,,Q:bad,9,8\n"
    r = c.post("/imports/employees", files={"file": ("e.csv", csv.encode(), "text/csv")})
    j = r.json()
    assert r.status_code == 200 and j["valid"] == 1 and j["errors"] == 2 and not j["committed"]
    assert c.post("/imports/employees?commit=true", files={"file": ("e.csv", csv.encode(), "text/csv")}
                  ).status_code == 422
    ok = "code,name\nA1,Zoé\n"
    assert c.post("/imports/employees?commit=true", files={"file": ("e.csv", ok.encode(), "text/csv")}
                  ).json()["created"] == 1
    assert c.post("/imports/employees", files={"file": ("e.exe", b"MZ", "application/octet-stream")}
                  ).status_code == 415


def test_demo_seed_refused_in_production(monkeypatch):
    from app import seed as seed_mod
    monkeypatch.setattr(seed_mod.settings, "app_env", "production")
    with pytest.raises(RuntimeError, match="refusé"):
        seed_mod.seed(domain=f"{uuid.uuid4().hex[:6]}.example")
    from app.config import Settings
    monkeypatch.delenv("APP_ENV", raising=False)
    assert Settings(_env_file=None).app_env == "production"  # défaut sûr
