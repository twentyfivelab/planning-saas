"""Cache des lectures d'affichage (lot 3, 20/11/2026) : partagé entre managers d'une même entreprise pour une même révision, jamais entre
périmètres différents (responsable de marque), jamais périmé après une modification. Données fictives."""
import uuid

from app import readcache
from tests.conftest import PW, make_client, register


def login(email):
    c = make_client()
    r = c.post("/auth/login", json={"email": email, "password": PW})
    assert r.status_code == 200, r.text
    c.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    return c


def test_cache_partage_sans_fuite_de_perimetre_ni_donnee_perimee():
    o = make_client()
    dom = f"cache-{uuid.uuid4().hex[:8]}.example"
    register(o, "Cache SA", f"owner@{dom}")
    assert o.post("/catalog/sites", json={"code": "S1", "name": "Site Un"}).status_code == 201
    for b in ("Alpha", "Beta"):
        assert o.post("/catalog/brands", json={"name": b}).status_code == 201
        assert o.post("/catalog/animations", json={"site_code": "S1", "brand_code": b, "start": "09:00", "end": "18:00", "weekdays": [0, 1, 2, 3, 4],
                                                   "headcount": 1, "from_month": "2026-12"}).status_code == 201
    emps = [o.post("/employees", json={"code": c, "name": c.capitalize(), "brands": {"Alpha": "priority", "Beta": "priority"}}).json() for c in ("ana", "ben", "cleo")]
    pid = o.post("/periods/ensure", json={"year": 2026, "month": 12}).json()["id"]
    r = o.post(f"/periods/{pid}/runs", json={"time_limit_s": 8}, headers={"Idempotency-Key": uuid.uuid4().hex})
    assert o.get(f"/runs/{r.json()['run_id']}").json()["status"] == "termine"
    for email, role in ((f"m1@{dom}", "manager"), (f"m2@{dom}", "manager"), (f"bm@{dom}", "brand_manager")):
        u = o.post("/users", json={"email": email, "name": role, "role": role, "password": PW}).json()
        if role == "brand_manager":
            assert o.patch(f"/users/{u['id']}", json={"scope_brands": ["Beta"]}).status_code == 200
    m1, m2, bm = login(f"m1@{dom}"), login(f"m2@{dom}"), login(f"bm@{dom}")
    readcache.clear()
    h0 = readcache.stats["hits"]
    full = m1.get(f"/periods/{pid}/schedule").json()["assignments"]
    assert m2.get(f"/periods/{pid}/schedule").json()["assignments"] == full and readcache.stats["hits"] == h0 + 1  # partagé entre managers
    assert {b for a in full for b in a["allocations"]} == {"Alpha", "Beta"}
    mine = bm.get(f"/periods/{pid}/schedule").json()["assignments"]
    assert mine and all(set(a["allocations"]) == {"Beta"} for a in mine)  # périmètre respecté malgré le cache chaud
    # après une modification, la lecture suivante est à jour (nouvelle révision), pour tous
    a = next(x for x in full if not x["locked"])
    busy = {x["employee_id"] for x in full if x["day"] == a["day"]}
    to = next(e for e in emps if e["id"] not in busy and e["id"] != a["employee_id"]) if any(e["id"] not in busy for e in emps) else None
    if to is None:  # jour complet : on libère le shift (retrait) pour garantir une modification visible
        assert m1.delete(f"/assignments/{a['assignment_id']}?force=true").status_code == 204
        assert all(x["assignment_id"] != a["assignment_id"] for x in m2.get(f"/periods/{pid}/schedule").json()["assignments"])
    else:
        assert m1.put(f"/assignments/{a['assignment_id']}", json={"employee_id": to["id"], "expected_employee_id": a["employee_id"]}).status_code == 200
        now = next(x for x in m2.get(f"/periods/{pid}/schedule").json()["assignments"] if x["assignment_id"] == a["assignment_id"])
        assert now["employee_id"] == to["id"]
