"""Espace collaborateur : demandes (congé, absence, échange) et circuit d'approbation. Données entièrement créées par les tests."""
import uuid

import pytest

from tests.conftest import make_client, register

PW = "Collab-Pass-For-Tests-42"


def login(email, pw=PW):
    c = make_client()
    r = c.post("/auth/login", json={"email": email, "password": pw})
    assert r.status_code == 200, r.text
    c.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    return c


@pytest.fixture
def t():
    o = make_client()
    dom = f"req-{uuid.uuid4().hex[:8]}.example"
    register(o, "Demandes SA", f"owner@{dom}")
    for code, name in (("AERO", "Aéroport"), ("GARE", "Gare")):
        assert o.post("/catalog/sites", json={"code": code, "name": name}).status_code == 201
    assert o.post("/catalog/brands", json={"name": "Alpha"}).status_code == 201
    for site in ("AERO", "GARE"):
        assert o.post("/catalog/animations", json={"site_code": site, "brand_code": "Alpha", "start": "09:00", "end": "18:00", "weekdays": [0, 1, 2, 3, 4, 5, 6],
                                                   "headcount": 1, "from_month": "2026-11"}).status_code == 201
    emps = {}
    for code in ("ana", "ben", "cleo", "dan"):
        emps[code] = o.post("/employees", json={"code": code, "name": code.capitalize(), "brands": {"Alpha": "priority"}}).json()
    pid = o.post("/periods/ensure", json={"year": 2026, "month": 11}).json()["id"]
    r = o.post(f"/periods/{pid}/runs", json={"time_limit_s": 8}, headers={"Idempotency-Key": uuid.uuid4().hex})
    assert r.status_code == 202
    users = {}
    for code in ("ana", "ben"):
        email = f"{code}@{dom}"
        r = o.post("/users", json={"email": email, "name": code.capitalize(), "role": "employee", "password": PW, "employee_id": emps[code]["id"]})
        assert r.status_code == 201, r.text
        users[code] = login(email)
    mgr = f"chef@{dom}"
    assert o.post("/users", json={"email": mgr, "name": "Chef", "role": "manager", "password": PW}).status_code == 201
    return dict(o=o, emps=emps, pid=pid, ana=users["ana"], ben=users["ben"], mgr=login(mgr))


def rows(o, pid):
    return o.get(f"/periods/{pid}/schedule").json()["assignments"]


def test_conge_demande_approuve_sans_retirer_de_shift(t):
    ana, mgr, o, pid = t["ana"], t["mgr"], t["o"], t["pid"]
    bad = ana.post("/me/requests", json={"kind": "leave", "start_date": "2026-11-20", "end_date": "2026-11-18"})
    assert bad.status_code == 422
    r = ana.post("/me/requests", json={"kind": "leave", "start_date": "2026-11-18", "end_date": "2026-11-19", "note": "mariage"})
    assert r.status_code == 201 and r.json()["status"] == "pending"
    rid = r.json()["id"]
    assert ana.get("/requests").status_code == 403  # un collaborateur ne voit pas les demandes des autres
    assert ana.post(f"/requests/{rid}/decide", json={"approve": True}).status_code == 403
    item = next(x for x in mgr.get("/requests").json() if x["id"] == rid)
    mine = [x for x in rows(o, pid) if x["employee_id"] == t["emps"]["ana"]["id"] and x["day"] in ("2026-11-18", "2026-11-19")]
    assert len(item["impact"]) == len(mine)  # shifts à remplacer affichés avant la décision
    before = rows(o, pid)
    d = mgr.post(f"/requests/{rid}/decide", json={"approve": True, "note": "bon mariage"})
    assert d.status_code == 200 and d.json()["status"] == "approved"
    leaves = [x for x in o.get("/leaves").json() if x["employee_id"] == t["emps"]["ana"]["id"]]
    assert [(x["start_date"], x["end_date"], x["status"]) for x in leaves] == [("2026-11-18", "2026-11-19", "approved")]
    assert rows(o, pid) == before  # rien n'est retiré automatiquement : les conflits apparaissent et se traitent par les remplacements
    notes = ana.get("/notifications").json()["items"]
    assert any(n["title"] == "Demande approuvée" and "bon mariage" in (n["body"] or "") for n in notes)
    assert mgr.post(f"/requests/{rid}/decide", json={"approve": False}).status_code == 409  # déjà traitée


def test_absence_partielle_demandee_puis_refusee_ou_appliquee(t):
    ana, mgr, o = t["ana"], t["mgr"], t["o"]
    r1 = ana.post("/me/requests", json={"kind": "absence", "on_date": "2026-11-24", "start_time": "08:00", "end_time": "10:00"}).json()
    r2 = ana.post("/me/requests", json={"kind": "absence", "on_date": "2026-11-25"}).json()
    r3 = ana.post("/me/requests", json={"kind": "absence", "on_date": "2026-11-26"}).json()
    assert mgr.post(f"/requests/{r1['id']}/decide", json={"approve": True}).status_code == 200
    pa = [x for x in o.get("/partial-absences").json() if x["employee_id"] == t["emps"]["ana"]["id"]]
    assert [(x["on_date"], x["start_time"][:5], x["end_time"][:5]) for x in pa] == [("2026-11-24", "08:00", "10:00")]
    assert mgr.post(f"/requests/{r2['id']}/decide", json={"approve": False, "note": "inventaire"}).json()["status"] == "refused"
    assert o.get(f"/employees/{t['emps']['ana']['id']}/availability").json()["dates"] == []  # refus : rien d'appliqué
    assert ana.post(f"/me/requests/{r3['id']}/cancel").json()["status"] == "cancelled"
    assert mgr.post(f"/requests/{r3['id']}/decide", json={"approve": True}).status_code == 409
    mine = ana.get("/me/requests").json()["mine"]
    assert {x["id"]: x["status"] for x in mine} == {r1["id"]: "approved", r2["id"]: "refused", r3["id"]: "cancelled"}


def test_echange_accord_du_collegue_puis_approbation_controlee(t):
    ana, ben, mgr, o, pid, emps = t["ana"], t["ben"], t["mgr"], t["o"], t["pid"], t["emps"]
    a = rows(o, pid)
    da = next(x for x in a if x["employee_id"] == emps["ana"]["id"])
    db_ = next(x for x in a if x["employee_id"] == emps["ben"]["id"] and x["day"] != da["day"])
    assert ana.post("/me/requests", json={"kind": "swap", "my_day": "2026-12-05", "colleague_id": emps["ben"]["id"], "colleague_day": db_["day"]}).status_code == 422
    r = ana.post("/me/requests", json={"kind": "swap", "my_day": da["day"], "colleague_id": emps["ben"]["id"], "colleague_day": db_["day"]})
    assert r.status_code == 201 and r.json()["status"] == "awaiting_colleague"
    rid = r.json()["id"]
    assert mgr.post(f"/requests/{rid}/decide", json={"approve": True}).status_code == 409  # accord du collègue d'abord
    assert t["ana"].post(f"/me/requests/{rid}/answer", json={"accept": True}).status_code == 404  # seul le collègue répond
    got = ben.get("/me/requests").json()["received"]
    assert [x["id"] for x in got] == [rid]
    assert ben.post(f"/me/requests/{rid}/answer", json={"accept": True}).json()["status"] == "pending"
    d = mgr.post(f"/requests/{rid}/decide", json={"approve": True})
    if d.status_code == 409 and d.json()["detail"]["code"] == "needs_confirmation":  # mêmes alertes qu'un échange fait à l'écran
        d = mgr.post(f"/requests/{rid}/decide", json={"approve": True, "force": True, "note": "accord des deux"})
    assert d.status_code == 200, d.text
    after = {x["assignment_id"]: x["employee_id"] for x in rows(o, pid)}
    assert after[da["assignment_id"]] == emps["ben"]["id"] and after[db_["assignment_id"]] == emps["ana"]["id"]
    assert any(n["title"] == "Demande approuvée" for n in ben.get("/notifications").json()["items"])


def test_echange_obsolete_si_le_planning_a_change(t):
    ana, ben, mgr, o, pid, emps = t["ana"], t["ben"], t["mgr"], t["o"], t["pid"], t["emps"]
    a = rows(o, pid)
    da = next(x for x in a if x["employee_id"] == emps["ana"]["id"])
    db_ = next(x for x in a if x["employee_id"] == emps["ben"]["id"] and x["day"] != da["day"])
    rid = ana.post("/me/requests", json={"kind": "swap", "my_day": da["day"], "colleague_id": emps["ben"]["id"], "colleague_day": db_["day"]}).json()["id"]
    ben.post(f"/me/requests/{rid}/answer", json={"accept": True})
    o.delete(f"/assignments/{da['assignment_id']}?force=true")  # le shift d'Ana a été retiré entre-temps
    assert next(x for x in mgr.get("/requests").json() if x["id"] == rid)["stale"] is True
    d = mgr.post(f"/requests/{rid}/decide", json={"approve": True})
    assert d.status_code == 409 and d.json()["detail"]["code"] == "stale"
    assert mgr.post(f"/requests/{rid}/decide", json={"approve": False, "note": "planning modifié"}).json()["status"] == "refused"


def test_compte_non_relie_et_cloisonnement(t):
    o = t["o"]
    dom = f"x-{uuid.uuid4().hex[:6]}.example"
    assert o.post("/users", json={"email": f"seul@{dom}", "name": "Seul", "role": "employee", "password": PW}).status_code == 201
    c = login(f"seul@{dom}")
    assert c.get("/me/requests").status_code == 403
    other = make_client()
    register(other, "Autre SA", f"autre-{uuid.uuid4().hex[:6]}@example.com")
    assert other.get("/requests").json() == []  # demandes d'un autre tenant invisibles (RLS)
