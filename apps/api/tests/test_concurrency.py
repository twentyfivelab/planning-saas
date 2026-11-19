"""Deux managers sur le même planning : jamais d'écrasement silencieux (refus explicite « modifié par quelqu'un d'autre », rien
n'est modifié), jamais de double affectation par des actions simultanées, jamais de double traitement après un double clic ou un
nouvel envoi. Données entièrement créées par les tests."""
import threading
import uuid

import pytest

from tests.conftest import PW, make_client, register


def login(email):
    c = make_client()
    r = c.post("/auth/login", json={"email": email, "password": PW})
    assert r.status_code == 200, r.text
    c.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    return c


@pytest.fixture
def t():
    a = make_client()
    dom = f"conc-{uuid.uuid4().hex[:8]}.example"
    register(a, "Concurrence SA", f"owner@{dom}")
    assert a.post("/catalog/sites", json={"code": "AERO", "name": "Aéroport"}).status_code == 201
    assert a.post("/catalog/brands", json={"name": "Alpha"}).status_code == 201
    assert a.post("/catalog/animations", json={"site_code": "AERO", "brand_code": "Alpha", "start": "09:00", "end": "17:00", "weekdays": [0, 1, 2, 3, 4],
                                               "headcount": 2, "from_month": "2026-12"}).status_code == 201
    emps = [a.post("/employees", json={"code": c, "name": c.capitalize(), "brands": {"Alpha": "priority"}}).json() for c in ("ana", "ben", "cleo", "dan", "eve", "fay")]
    assert a.post("/users", json={"email": f"m2@{dom}", "name": "Manager deux", "role": "admin", "password": PW}).status_code == 201
    b = login(f"m2@{dom}")
    pid = a.post("/periods/ensure", json={"year": 2026, "month": 12}).json()["id"]
    assert a.post(f"/periods/{pid}/runs", json={"time_limit_s": 8}, headers={"Idempotency-Key": uuid.uuid4().hex}).status_code == 202
    return dict(a=a, b=b, pid=pid, emps=emps)


def rows(c, pid):
    return c.get(f"/periods/{pid}/schedule").json()["assignments"]


def free_for(c, pid, x, exclude=()):
    """Un collaborateur sans shift ce jour-là (autre que le titulaire)."""
    busy = {r["employee_id"] for r in rows(c, pid) if r["day"] == x["day"]}
    return next(e["id"] for e in c.get("/employees").json() if e["id"] not in busy and e["id"] not in exclude)


def test_deplacement_concurrent_jamais_ecrase(t):
    a, b, pid = t["a"], t["b"], t["pid"]
    x = next(r for r in rows(a, pid) if not r["locked"])
    seen = x["employee_id"]  # ce que les deux managers voient
    e1 = free_for(a, pid, x)
    e2 = free_for(a, pid, x, exclude=(e1,))
    assert a.put(f"/assignments/{x['assignment_id']}", json={"employee_id": e1, "expected_employee_id": seen}).status_code == 200
    r = b.put(f"/assignments/{x['assignment_id']}", json={"employee_id": e2, "expected_employee_id": seen})  # vue périmée
    assert r.status_code == 409 and r.json()["detail"]["code"] == "stale" and "modifié par quelqu'un d'autre" in r.json()["detail"]["message"]
    assert next(z for z in rows(a, pid) if z["assignment_id"] == x["assignment_id"])["employee_id"] == e1  # rien n'a été écrasé
    # double clic du premier manager : même résultat, rien n'est refait
    again = a.put(f"/assignments/{x['assignment_id']}", json={"employee_id": e1, "expected_employee_id": seen})
    assert again.status_code == 200 and again.json().get("already") is True


def test_deplacements_simultanes_un_seul_applique(t):
    a, b, pid = t["a"], t["b"], t["pid"]
    x = next(r for r in rows(a, pid) if not r["locked"])
    seen = x["employee_id"]
    e1 = free_for(a, pid, x)
    e2 = free_for(a, pid, x, exclude=(e1,))
    res = [None, None]
    go = threading.Barrier(2)

    def run(i, c, e):
        go.wait()
        res[i] = c.put(f"/assignments/{x['assignment_id']}", json={"employee_id": e, "expected_employee_id": seen})
    th = [threading.Thread(target=run, args=(0, a, e1)), threading.Thread(target=run, args=(1, b, e2))]
    [z.start() for z in th]
    [z.join() for z in th]
    assert sorted(r.status_code for r in res) == [200, 409], [r.text for r in res]
    winner = e1 if res[0].status_code == 200 else e2
    after = [z for z in rows(a, pid) if z["shift_id"] == x["shift_id"]]
    assert [z["employee_id"] for z in after] == [winner]  # une seule affectation, celle qui a gagné


def test_horaires_echange_retrait_et_transfert_groupe_proteges(t):
    a, b, pid = t["a"], t["b"], t["pid"]
    r0 = [r for r in rows(a, pid) if not r["locked"]]
    x = r0[0]
    seen = {"expected_start": x["start"], "expected_end": x["end"], "expected_break": x["break_minutes"]}
    ok = a.patch(f"/shifts/{x['shift_id']}", json={"start_time": "09:00:00", "end_time": "16:00:00", "break_minutes": 60, **seen})
    assert ok.status_code == 200, ok.text
    st = b.patch(f"/shifts/{x['shift_id']}", json={"start_time": "10:00:00", "end_time": "17:00:00", "break_minutes": 60, **seen})
    assert st.status_code == 409 and st.json()["detail"]["code"] == "stale"
    assert a.patch(f"/shifts/{x['shift_id']}", json={"start_time": "09:00:00", "end_time": "16:00:00", "break_minutes": 60, **seen}).json().get("already") is True
    # échange : un titulaire a changé entre-temps -> refus, rien n'est échangé
    p, q = next((p, q) for p in r0[1:] for q in r0[1:] if p["day"] != q["day"] and p["employee_id"] != q["employee_id"])
    e1 = free_for(a, pid, p, exclude=(q["employee_id"],))
    assert a.put(f"/assignments/{p['assignment_id']}", json={"employee_id": e1, "expected_employee_id": p["employee_id"]}).status_code == 200
    sw = b.post(f"/periods/{pid}/swap", json={"a": p["assignment_id"], "b": q["assignment_id"], "expected_a": p["employee_id"], "expected_b": q["employee_id"]})
    assert sw.status_code == 409 and sw.json()["detail"]["code"] == "stale"
    assert {z["assignment_id"]: z["employee_id"] for z in rows(a, pid)}[q["assignment_id"]] == q["employee_id"]
    # retrait sur une vue périmée : refus ; retrait d'un shift déjà retiré : « déjà retiré » (404), jamais une erreur obscure
    d = b.delete(f"/assignments/{p['assignment_id']}", params={"expected_employee_id": p["employee_id"], "force": True})
    assert d.status_code == 409 and d.json()["detail"]["code"] == "stale"
    assert a.delete(f"/assignments/{p['assignment_id']}", params={"expected_employee_id": e1, "force": True}).status_code == 204
    gone = b.delete(f"/assignments/{p['assignment_id']}", params={"expected_employee_id": e1, "force": True})
    assert gone.status_code == 404 and gone.json()["detail"]["code"] == "gone"
    # transfert groupé : un seul shift modifié ailleurs -> toute l'opération est refusée
    y, z = [r for r in rows(a, pid) if not r["locked"] and r["assignment_id"] != p["assignment_id"]][:2]
    target = free_for(a, pid, y, exclude=(z["employee_id"],))
    bt = b.post(f"/periods/{pid}/bulk-transfer", json={"operations": [{"assignment_id": y["assignment_id"], "to_employee_id": target, "expected_from": y["employee_id"]},
                                                                     {"assignment_id": z["assignment_id"], "to_employee_id": target, "expected_from": "00000000-0000-0000-0000-000000000000"}], "force": True})
    assert bt.status_code == 409 and bt.json()["detail"]["code"] == "stale"
    assert {r["assignment_id"]: r["employee_id"] for r in rows(a, pid)}[y["assignment_id"]] == y["employee_id"]  # tout ou rien


def test_attribution_manuelle_double_clic_et_nouvel_envoi(t):
    a, pid = t["a"], t["pid"]
    x = next(r for r in rows(a, pid) if not r["locked"])
    e1 = free_for(a, pid, x)
    body = {"employee_id": e1, "shift_id": x["shift_id"], "force": True, "reason": "test", "expected_from": x["employee_id"]}
    r1 = a.post(f"/periods/{pid}/manual-assign", json=body)
    assert r1.status_code == 200, r1.text
    r2 = a.post(f"/periods/{pid}/manual-assign", json=body)  # même envoi (double clic, reprise après coupure)
    assert r2.status_code == 200 and r2.json()["already"] is True
    assert len([z for z in rows(a, pid) if z["shift_id"] == x["shift_id"]]) == 1
    hist = [h for h in a.get("/history", params={"kind": "replace"}).json()["items"] if x["day"] in (h.get("shift_days") or [])]
    assert len([h for h in hist if "test" in (h.get("reason") or "")]) <= 1  # une seule trace pour l'opération
