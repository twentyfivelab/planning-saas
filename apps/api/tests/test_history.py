"""Historique des modifications : langage simple, date de modification ≠ date du shift, fuseau de l'entreprise, opérations réussies
seulement, opérations groupées résumées avec détail, filtres, droits, collaborateur retiré toujours lisible."""
import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from tests.conftest import make_client, register

PW = "History-Pass-For-Tests-42"
NOV = (2026, 11)


def login(email):
    c = make_client()
    r = c.post("/auth/login", json={"email": email, "password": PW})
    assert r.status_code == 200, r.text
    c.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    return c


@pytest.fixture
def t():
    o = make_client()
    dom = f"hist-{uuid.uuid4().hex[:8]}.example"
    register(o, "Historique SA", f"owner@{dom}")
    for code, name in (("AERO", "Aéroport"), ("GARE", "Gare")):
        assert o.post("/catalog/sites", json={"code": code, "name": name}).status_code == 201
    for b in ("Alpha", "Beta"):
        assert o.post("/catalog/brands", json={"name": b}).status_code == 201
    for site, b in (("AERO", "Alpha"), ("GARE", "Beta")):
        assert o.post("/catalog/animations", json={"site_code": site, "brand_code": b, "start": "09:00", "end": "18:00", "weekdays": [0, 1, 2, 3, 4, 5, 6],
                                                   "headcount": 1, "from_month": "2026-11"}).status_code == 201
    emps = {code: o.post("/employees", json={"code": code, "name": code.capitalize(), "brands": {"Alpha": "priority", "Beta": "priority"}}).json()
            for code in ("ana", "ben", "cleo", "dan")}
    pid = o.post("/periods/ensure", json={"year": 2026, "month": 11}).json()["id"]
    r = o.post(f"/periods/{pid}/runs", json={"time_limit_s": 8}, headers={"Idempotency-Key": uuid.uuid4().hex})
    assert r.status_code == 202
    return dict(o=o, emps=emps, pid=pid, dom=dom)


def rows(o, pid):
    return o.get(f"/periods/{pid}/schedule").json()["assignments"]


def hist(c, **q):
    r = c.get("/history", params={k: v for k, v in q.items() if v is not None})
    assert r.status_code == 200, r.text
    return r.json()


def test_generation_remplacement_horaires_suppression_en_langage_simple(t):
    o, pid, emps = t["o"], t["pid"], t["emps"]
    h = hist(o)
    gen = next(i for i in h["items"] if i["kind"] == "generation")
    assert gen["title"] == "Génération du planning" and gen["by"] == "Historique SA" and gen["period"] == "Novembre 2026"
    assert gen["lines"][0].endswith("affectation(s) enregistrée(s)") or "affectation(s) enregistrée(s)" in gen["lines"][0]
    a = rows(o, pid)
    x = next(r for r in a if r["site"] == "AERO" and not r["locked"])
    holder = next(e for e in emps.values() if e["id"] == x["employee_id"])
    busy = {r["employee_id"] for r in a if r["day"] == x["day"]}
    to = next(e for e in emps.values() if e["id"] not in busy)
    before = datetime.now(timezone.utc)
    r = o.post(f"/periods/{pid}/manual-assign", json={"employee_id": to["id"], "shift_id": x["shift_id"], "force": True, "reason": "test"})
    assert r.status_code == 200, r.text
    ev = hist(o, kind="replace")["items"][0]
    assert ev["title"] == "Remplacement sur Alpha" and ev["lines"][0] == f"{holder['name']} → {to['name']}" and ev["by"] == "Historique SA"
    d = datetime.fromisoformat(x["day"])
    assert ev["shift_days"] == [x["day"]] and ev["shift_day_label"].endswith(f"{d.day} novembre 2026")  # date du shift
    at = datetime.fromisoformat(ev["at"]).astimezone(ZoneInfo("Europe/Zurich"))  # date de modification, fuseau de l'entreprise
    assert at >= before.astimezone(ZoneInfo("Europe/Zurich")) and ev["at_label"].endswith(f"à {at:%H:%M}") and h["timezone"] == "Europe/Zurich"
    # changement d'horaires : ancienne et nouvelle valeur
    y = next(r for r in rows(o, pid) if not r["locked"] and r["site"] == "GARE")
    who = next(e for e in emps.values() if e["id"] == y["employee_id"])
    assert o.patch(f"/shifts/{y['shift_id']}", json={"start_time": "09:00", "end_time": "17:00", "break_minutes": 60}).status_code == 200
    ev = hist(o, kind="hours")["items"][0]
    assert ev["title"] == "Modification d'horaires sur Beta" and ev["lines"][0] == f"{who['name']} : 09:00–18:00 → 09:00–17:00"
    # suppression
    z = next(r for r in rows(o, pid) if r["assignment_id"] != x["assignment_id"])
    zname = next(e["name"] for e in emps.values() if e["id"] == z["employee_id"])
    assert o.delete(f"/assignments/{z['assignment_id']}?force=true").status_code == 204
    ev = hist(o, kind="remove")["items"][0]
    assert ev["title"].startswith("Suppression d'un shift") and ev["lines"][0].startswith(f"{zname} : ")


def test_operation_refusee_absente_de_l_historique(t):
    o, pid, emps = t["o"], t["pid"], t["emps"]
    n = len(hist(o)["items"])
    x = rows(o, pid)[0]
    cap = o.get("/settings/monthly-cap").json()["minutes"]
    try:
        o.put("/settings/monthly-cap", json={"hours": 1})  # tout transfert dépasserait le plafond : refusé, non dérogeable
        other = next(e for e in emps.values() if e["id"] != x["employee_id"])
        r = o.post(f"/periods/{pid}/manual-assign", json={"employee_id": other["id"], "shift_id": x["shift_id"], "force": True})
        assert r.status_code == 409
    finally:
        o.put("/settings/monthly-cap", json={"hours": cap / 60 if cap else None})
    assert len(hist(o)["items"]) == n  # rien n'est enregistré pour une opération refusée


def test_operation_groupee_resumee_avec_detail_et_echange(t):
    o, pid, emps = t["o"], t["pid"], t["emps"]
    a = rows(o, pid)
    cleo = emps["cleo"]["id"]
    cdays = {r["day"] for r in a if r["employee_id"] == cleo}
    mine = [r for r in a if r["employee_id"] == emps["ana"]["id"] and r["day"] not in cdays][:3]
    r = o.post(f"/periods/{pid}/bulk-transfer", json={"operations": [{"assignment_id": x["assignment_id"], "to_employee_id": cleo} for x in mine], "force": True})
    assert r.status_code == 200, r.text
    ev = hist(o, kind="bulk")["items"][0]
    assert ev["title"].startswith("Modification groupée : 3 shifts") and len(ev["details"]) == 3
    assert sorted(ev["shift_days"]) == sorted(x["day"] for x in mine) and ev["shift_day_label"].startswith("du ")
    assert all(dd["lines"][0].startswith("Ana → Cleo") for dd in ev["details"])
    # échange
    a = rows(o, pid)
    A = next(x for x in a if x["employee_id"] == emps["ben"]["id"])
    B = next(x for x in a if x["employee_id"] == emps["dan"]["id"] and x["day"] != A["day"])
    r = o.post(f"/periods/{pid}/swap", json={"a": A["assignment_id"], "b": B["assignment_id"], "force": True})
    assert r.status_code == 200, r.text
    ev = hist(o, kind="swap")["items"][0]
    assert ev["lines"][0] == "Ben ↔ Dan" and sorted(ev["shift_days"]) == sorted([A["day"], B["day"]])


def test_filtres_droits_et_collaborateur_retire(t):
    o, pid, emps, dom = t["o"], t["pid"], t["emps"], t["dom"]
    a = rows(o, pid)
    x = next(r for r in a if r["site"] == "AERO")
    busy = {r["employee_id"] for r in a if r["day"] == x["day"]}
    to = next(e for e in emps.values() if e["id"] not in busy)
    assert o.post(f"/periods/{pid}/manual-assign", json={"employee_id": to["id"], "shift_id": x["shift_id"], "force": True}).status_code == 200
    h = hist(o)
    assert {k["key"] for k in h["kinds"]} >= {"add", "remove", "replace", "swap", "bulk", "hours", "generation", "restore", "publish"}
    assert all(to["id"] in [e["id"] for e in i["employees"]] for i in hist(o, employee_id=to["id"])["items"])
    assert all("AERO" in i["sites"] for i in hist(o, site="AERO")["items"]) and hist(o, site="AERO")["items"]
    assert all("Beta" in i["brands"] for i in hist(o, brand="Beta")["items"])
    me = o.get("/auth/me").json()["id"]
    assert hist(o, user_id=me)["items"] and hist(o, user_id=str(uuid.uuid4()))["items"] == []
    assert hist(o, period_id=pid)["items"] and hist(o, period_id=str(uuid.uuid4()))["items"] == []
    assert hist(o, **{"from": "2030-01-01"})["items"] == []
    assert o.get("/history?kind=inconnu").status_code == 422
    # responsable de marque : seulement sa marque
    u = o.post("/users", json={"email": f"rm@{dom}", "name": "Resp Alpha", "role": "brand_manager", "password": PW})
    assert u.status_code == 201, u.text
    assert o.patch(f"/users/{u.json()['id']}", json={"scope_brands": ["Alpha"]}).status_code == 200
    rm = login(f"rm@{dom}")
    items = hist(rm)["items"]
    assert items and all("Alpha" in i["brands"] for i in items)
    # collaborateur : pas d'accès à l'historique du planning
    assert o.post("/users", json={"email": f"col@{dom}", "name": "Col", "role": "employee", "password": PW, "employee_id": emps["ana"]["id"]}).status_code == 201
    assert login(f"col@{dom}").get("/history").status_code == 403
    # collaborateur retiré : ses événements restent lisibles avec son nom
    assert o.delete(f"/employees/{to['id']}").status_code in (200, 204)
    ev = next(i for i in hist(o, kind="replace")["items"] if i["shift_days"] == [x["day"]])
    assert to["name"] in ev["lines"][0]
