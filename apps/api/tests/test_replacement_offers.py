"""Propositions de remplacement envoyées aux collaborateurs : l'affectation actuelle reste en place jusqu'à l'acceptation validée ;
refus, expiration, annulation ou caducité ne laissent jamais le shift vacant ; acceptation revérifiée et appliquée en une opération.
Données entièrement créées par les tests."""
import threading
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import text

from tests.conftest import PW, make_client, register


def login(email):
    c = make_client()
    r = c.post("/auth/login", json={"email": email, "password": PW})
    assert r.status_code == 200, r.text
    c.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    return c


@pytest.fixture
def t():
    o = make_client()
    dom = f"rep-{uuid.uuid4().hex[:8]}.example"
    register(o, "Remplacements SA", f"owner@{dom}")
    assert o.post("/catalog/sites", json={"code": "AERO", "name": "Aéroport"}).status_code == 201
    assert o.post("/catalog/brands", json={"name": "Nuxe"}).status_code == 201
    assert o.post("/catalog/animations", json={"site_code": "AERO", "brand_code": "Nuxe", "start": "09:00", "end": "17:00", "weekdays": [0, 1, 2, 3, 4, 5, 6],
                                               "headcount": 2, "from_month": "2026-12"}).status_code == 201
    emps, users = {}, {}
    for code in ("ana", "ben", "cleo", "dan", "eve", "fay"):
        emps[code] = o.post("/employees", json={"code": code, "name": code.capitalize(), "brands": {"Nuxe": "priority"}}).json()
        if code != "fay":  # fay : aucun compte relié à sa fiche
            assert o.post("/users", json={"email": f"{code}@{dom}", "name": code.capitalize(), "role": "employee", "password": PW,
                                          "employee_id": emps[code]["id"]}).status_code == 201
            users[code] = login(f"{code}@{dom}")
    pid = o.post("/periods/ensure", json={"year": 2026, "month": 12}).json()["id"]
    r = o.post(f"/periods/{pid}/runs", json={"time_limit_s": 8}, headers={"Idempotency-Key": uuid.uuid4().hex})
    assert r.status_code == 202 and o.get(f"/runs/{r.json()['run_id']}").json()["status"] == "termine"
    return dict(o=o, pid=pid, emps=emps, users=users, dom=dom, by_id={v["id"]: k for k, v in emps.items()})


def sched(o, pid):
    return o.get(f"/periods/{pid}/schedule").json()["assignments"]


def pick(t, day=None):
    """Un shift tenu, et ses remplaçants compatibles (dans l'ordre du classement), avec un compte."""
    o = t["o"]
    for a in sched(o, t["pid"]):
        if day and a["day"] != day:
            continue
        rk = o.get(f"/shifts/{a['shift_id']}/replacements").json()
        ok = [c["employee_uuid"] for c in rk["candidates"] if c["status"] == "compatible" and t["by_id"].get(c["employee_uuid"]) in t["users"]]
        if len(ok) >= 2:
            return a, ok
    pytest.skip("aucun shift avec deux remplaçants compatibles")


def holder(o, pid, shift_id):
    return [(x["employee_id"], x["assignment_id"]) for x in sched(o, pid) if x["shift_id"] == shift_id]


def launch(o, shift_id, first, minutes=240):
    r = o.post(f"/shifts/{shift_id}/replacement-requests", json={"start_employee_id": first, "response_minutes": minutes})
    assert r.status_code == 201, r.text
    return r.json()


def notes(c, kind):
    return [n for n in c.get("/notifications").json()["items"] if n["kind"] == kind]


def test_acceptation_validee_puis_double_clic(t):
    o, pid, users, by_id = t["o"], t["pid"], t["users"], t["by_id"]
    a, cands = pick(t)
    before = holder(o, pid, a["shift_id"])
    req = launch(o, a["shift_id"], cands[0])
    first = by_id[cands[0]]
    assert req["status"] == "open" and req["pending"]["employee"]["name"] == first.capitalize()
    assert holder(o, pid, a["shift_id"]) == before  # l'affectation actuelle reste en place pendant l'attente
    # une seule proposition par shift
    again = o.post(f"/shifts/{a['shift_id']}/replacement-requests", json={"start_employee_id": cands[1], "response_minutes": 60})
    assert again.status_code == 409 and again.json()["detail"]["code"] == "already_open"
    # le collaborateur : notification (date, horaires, site, marque) et proposition avec échéance, jamais après le début du shift
    c = users[first]
    n = notes(c, "replacement_offer")
    assert len(n) == 1 and "09:00–17:00, Aéroport, Nuxe" in n[0]["body"] and "Réponse attendue avant le" in n[0]["body"]
    mine = c.get("/me/replacement-offers").json()["items"]
    assert len(mine) == 1 and mine[0]["status"] == "pending" and mine[0]["details"]["site"] == "Aéroport" and mine[0]["details"]["brands"] == ["Nuxe"]
    assert mine[0]["deadline"] <= f"{a['day']}T09:00" or mine[0]["deadline"][:10] <= a["day"]
    # droits : un autre collaborateur et le manager (sans fiche) ne voient ni n'acceptent cette proposition
    other = next(k for k in users if k != first and t["emps"][k]["id"] != before[0][0])
    assert users[other].post(f"/replacement-offers/{mine[0]['id']}/accept").status_code == 404
    assert o.post(f"/replacement-offers/{mine[0]['id']}/accept").status_code == 404
    assert users[other].get("/me/replacement-offers").json()["items"] == [] or all(x["id"] != mine[0]["id"] for x in users[other].get("/me/replacement-offers").json()["items"])
    # acceptation : transfert en une opération, verrouillé
    r = c.post(f"/replacement-offers/{mine[0]['id']}/accept")
    assert r.status_code == 200 and r.json()["already"] is False, r.text
    after = holder(o, pid, a["shift_id"])
    assert after == [(cands[0], before[0][1])]  # même affectation, nouveau titulaire : jamais de double affectation
    assert next(x for x in sched(o, pid) if x["shift_id"] == a["shift_id"])["locked"] is True
    # double clic : même résultat, rien de plus
    r2 = c.post(f"/replacement-offers/{mine[0]['id']}/accept")
    assert r2.status_code == 200 and r2.json()["already"] is True
    assert len(holder(o, pid, a["shift_id"])) == 1
    assert len(notes(o, "replacement_update")) == 1 and "a accepté de reprendre le shift" in notes(o, "replacement_update")[0]["body"]
    # ancien titulaire prévenu ; historique complet avec auteurs
    old = by_id[before[0][0]]
    if old in users:
        assert any("est repris par" in x["body"] for x in notes(users[old], "replacement_update"))
    h = o.get("/history", params={"kind": "proposal"}).json()["items"]
    titles = [x["title"] for x in h]
    # l'acceptation vient après ; lancement et envoi au premier candidat sont écrits dans la MÊME transaction (même horodatage) :
    # leur ordre relatif n'est pas défini (constaté le 19/11 : ordre aléatoire selon l'identifiant), seule leur présence est vérifiée
    assert titles[0] == f"Proposition acceptée par {first.capitalize()}"
    assert set(titles[1:3]) == {f"Proposition envoyée à {first.capitalize()}", "Proposition de remplacement lancée"}
    assert h[1]["at"] == h[2]["at"] and h[0]["at"] >= h[1]["at"]
    assert h[0]["by"] == first.capitalize() and {h[1]["by"], h[2]["by"]} == {o.get("/auth/me").json()["name"]}
    rep = o.get("/history", params={"kind": "replace"}).json()["items"][0]
    assert rep["title"].startswith("Remplacement") and f"→ {first.capitalize()}" in rep["lines"][0]


def test_refus_expiration_puis_epuisement_sans_shift_vacant(t):
    o, pid, users, by_id = t["o"], t["pid"], t["users"], t["by_id"]
    a, cands = pick(t)
    before = holder(o, pid, a["shift_id"])
    req = launch(o, a["shift_id"], cands[0])
    c1 = users[by_id[cands[0]]]
    oid = c1.get("/me/replacement-offers").json()["items"][0]["id"]
    r = c1.post(f"/replacement-offers/{oid}/refuse", json={"reason": "indisponible ce soir-là"})
    assert r.status_code == 200
    v = o.get(f"/shifts/{a['shift_id']}/replacement-request").json()["request"]
    assert v["status"] == "open" and v["pending"]["employee"]["id"] == cands[1]  # candidat suivant, selon le classement
    assert holder(o, pid, a["shift_id"]) == before
    assert c1.post(f"/replacement-offers/{oid}/accept").status_code == 409  # un refus n'est pas réversible
    # expiration : échéance dépassée -> candidat suivant (ou épuisement), titulaire conservé
    from app.db import tenant_session
    tid = o.get("/auth/me").json()["tenant_id"]
    with tenant_session(tid) as db:
        db.execute(text("update replacement_offers set deadline_at = now() - interval '1 minute' where id = :i"), {"i": v["pending"]["id"]})
    v = o.get(f"/shifts/{a['shift_id']}/replacement-request").json()["request"]
    assert [x["status"] for x in v["offers"]][:2] == ["refused", "expired"]
    # tous les suivants refusent : épuisée, titulaire conservé, manager prévenu une fois
    while v["status"] == "open":
        nxt = users[by_id[v["pending"]["employee"]["id"]]]
        assert nxt.post(f"/replacement-offers/{v['pending']['id']}/refuse", json={}).status_code == 200
        v = o.get(f"/shifts/{a['shift_id']}/replacement-request").json()["request"]
    assert v["status"] == "exhausted" and holder(o, pid, a["shift_id"]) == before
    ex = [n for n in notes(o, "replacement_update") if n["title"] == "Remplacement non trouvé"]
    assert len(ex) == 1 and "reste affecté" in ex[0]["body"]
    assert req["id"] == v["id"]


def test_annulation_par_le_manager(t):
    o, pid, users, by_id = t["o"], t["pid"], t["users"], t["by_id"]
    a, cands = pick(t)
    before = holder(o, pid, a["shift_id"])
    req = launch(o, a["shift_id"], cands[0])
    c1 = users[by_id[cands[0]]]
    oid = c1.get("/me/replacement-offers").json()["items"][0]["id"]
    assert o.post(f"/replacement-requests/{req['id']}/cancel").json()["status"] == "cancelled"
    r = c1.post(f"/replacement-offers/{oid}/accept")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "offer_cancelled" and "annulée par votre responsable" in r.json()["detail"]["message"]
    assert holder(o, pid, a["shift_id"]) == before
    assert any(n["title"] == "Proposition de remplacement annulée" for n in notes(c1, "replacement_cancelled"))
    assert o.post(f"/replacement-requests/{req['id']}/cancel").status_code == 409
    # une nouvelle demande peut ensuite être lancée
    assert launch(o, a["shift_id"], cands[1])["status"] == "open"


def test_shift_modifie_ou_remplace_pendant_l_attente(t):
    o, pid, users, by_id, emps = t["o"], t["pid"], t["users"], t["by_id"], t["emps"]
    a, cands = pick(t)
    launch(o, a["shift_id"], cands[0])
    c1 = users[by_id[cands[0]]]
    oid = c1.get("/me/replacement-offers").json()["items"][0]["id"]
    # le manager attribue directement le shift à un autre : la proposition devient caduque aussitôt (manager et collaborateur prévenus)
    other = next(e["id"] for k, e in emps.items() if e["id"] not in (cands[0], a["employee_id"]) and k in users
                 and not any(x["day"] == a["day"] and x["employee_id"] == e["id"] for x in sched(o, pid)))
    r = o.post(f"/periods/{pid}/manual-assign", json={"employee_id": other, "shift_id": a["shift_id"], "force": True, "reason": "test", "expected_from": a["employee_id"]})
    assert r.status_code == 200, r.text
    v = o.get(f"/shifts/{a['shift_id']}/replacement-request").json()["request"]
    assert v["status"] == "invalidated" and "déjà été attribué" in v["closed_reason"]
    acc = c1.post(f"/replacement-offers/{oid}/accept")
    assert acc.status_code == 409 and "n'est plus valable" in acc.json()["detail"]["message"]
    assert holder(o, pid, a["shift_id"])[0][0] == other  # jamais appliquée
    assert any("plus valable" in n["title"] for n in notes(c1, "replacement_cancelled"))
    assert any("caduque" in n["title"] for n in notes(o, "replacement_update"))
    # horaires modifiés pendant l'attente sur un autre shift
    b, cands2 = None, None
    for x in sched(o, pid):
        if x["shift_id"] == a["shift_id"]:
            continue
        rk = o.get(f"/shifts/{x['shift_id']}/replacements").json()
        ok = [c["employee_uuid"] for c in rk["candidates"] if c["status"] == "compatible" and by_id.get(c["employee_uuid"]) in users]
        if ok:
            b, cands2 = x, ok
            break
    assert b is not None
    launch(o, b["shift_id"], cands2[0])
    oid2 = users[by_id[cands2[0]]].get("/me/replacement-offers").json()["items"][0]["id"]
    assert o.patch(f"/shifts/{b['shift_id']}", json={"start_time": "10:00:00", "end_time": "17:00:00", "break_minutes": 60}).status_code == 200
    acc = users[by_id[cands2[0]]].post(f"/replacement-offers/{oid2}/accept")
    assert acc.status_code == 409 and "horaires" in acc.json()["detail"]["message"]
    assert holder(o, pid, b["shift_id"])[0][0] == b["employee_id"]


def test_nouvelle_absence_avant_acceptation(t):
    o, pid, users, by_id = t["o"], t["pid"], t["users"], t["by_id"]
    a, cands = pick(t)
    before = holder(o, pid, a["shift_id"])
    launch(o, a["shift_id"], cands[0])
    c1 = users[by_id[cands[0]]]
    oid = c1.get("/me/replacement-offers").json()["items"][0]["id"]
    assert o.post(f"/periods/{pid}/absences", json={"employee_id": cands[0], "start": a["day"], "end": a["day"], "reason": "maladie"}).status_code == 200
    r = c1.post(f"/replacement-offers/{oid}/accept")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "offer_blocked" and "indisponible" in r.json()["detail"]["message"]
    assert holder(o, pid, a["shift_id"]) == before
    v = o.get(f"/shifts/{a['shift_id']}/replacement-request").json()["request"]
    assert v["offers"][0]["status"] == "invalidated" and (v["status"] == "exhausted" or v["pending"]["employee"]["id"] == cands[1])


def test_acceptations_simultanees_jamais_de_double_affectation(t):
    """Même proposition acceptée deux fois en même temps (deux onglets) ; et deux propositions du même jour au même collaborateur
    acceptées en même temps : une seule affectation par shift, jamais deux shifts le même jour."""
    o, pid, users, by_id = t["o"], t["pid"], t["users"], t["by_id"]
    a, cands = pick(t)
    launch(o, a["shift_id"], cands[0])
    code = by_id[cands[0]]
    tabs = [users[code], login(f"{code}@{t['dom']}")]
    oid = tabs[0].get("/me/replacement-offers").json()["items"][0]["id"]
    res = [None, None]
    go = threading.Barrier(2)

    def run(i):
        go.wait()
        res[i] = tabs[i].post(f"/replacement-offers/{oid}/accept")
    th = [threading.Thread(target=run, args=(i,)) for i in range(2)]
    [x.start() for x in th]
    [x.join() for x in th]
    assert sorted(r.status_code for r in res) == [200, 200] and sorted(r.json()["already"] for r in res) == [False, True]
    assert len(holder(o, pid, a["shift_id"])) == 1 and holder(o, pid, a["shift_id"])[0][0] == cands[0]
    # en base : jamais deux propositions en attente pour un même shift
    from app.db import tenant_session
    tid = o.get("/auth/me").json()["tenant_id"]
    with pytest.raises(Exception):
        with tenant_session(tid) as db:
            rid = db.execute(text("select request_id from replacement_offers where id = :i"), {"i": oid}).scalar()
            for _ in range(2):
                db.execute(text("insert into replacement_offers (id, tenant_id, request_id, shift_id, employee_id, rank, status, deadline_at) "
                                "values (gen_random_uuid(), :t, :r, :s, :e, 9, 'pending', now() + interval '1 hour')"),
                           {"t": tid, "r": rid, "s": a["shift_id"], "e": cands[1]})
    # deux shifts du même jour proposés au même collaborateur, acceptés en même temps : un seul est appliqué
    day_shifts = {}
    for x in sched(o, pid):
        day_shifts.setdefault(x["day"], []).append(x)
    target = None
    for day, xs in sorted(day_shifts.items()):
        if len(xs) < 2 or day == a["day"]:
            continue
        free = [k for k in users if t["emps"][k]["id"] not in {y["employee_id"] for y in xs}]
        for k in free:
            ids = []
            for y in xs[:2]:
                rk = o.get(f"/shifts/{y['shift_id']}/replacements").json()
                if any(c["employee_uuid"] == t["emps"][k]["id"] and c["status"] == "compatible" for c in rk["candidates"]):
                    ids.append(y["shift_id"])
            if len(ids) == 2:
                target = (k, ids)
                break
        if target:
            break
    if target is None:
        pytest.skip("aucun jour avec deux shifts proposables au même collaborateur")
    k, ids = target
    for sid in ids:
        launch(o, sid, t["emps"][k]["id"])
    offs = [x["id"] for x in users[k].get("/me/replacement-offers").json()["items"] if x["status"] == "pending"]
    assert len(offs) == 2
    c2 = login(f"{k}@{t['dom']}")
    res = [None, None]
    go = threading.Barrier(2)

    def run2(i):
        go.wait()
        res[i] = (users[k] if i == 0 else c2).post(f"/replacement-offers/{offs[i]}/accept")
    th = [threading.Thread(target=run2, args=(i,)) for i in range(2)]
    [x.start() for x in th]
    [x.join() for x in th]
    assert sorted(r.status_code for r in res) == [200, 409], [r.text for r in res]
    mine_that_day = [x for x in sched(o, pid) if x["employee_id"] == t["emps"][k]["id"] and x["day"] == next(y["day"] for y in sched(o, pid) if y["shift_id"] == ids[0])]
    assert len(mine_that_day) == 1


def test_sans_compte_et_trop_tard(t):
    o, pid, emps = t["o"], t["pid"], t["emps"]
    for a in sched(o, pid):
        rk = o.get(f"/shifts/{a['shift_id']}/replacements").json()
        if any(c["employee_uuid"] == emps["fay"]["id"] and c["status"] == "compatible" for c in rk["candidates"]):
            r = o.post(f"/shifts/{a['shift_id']}/replacement-requests", json={"start_employee_id": emps["fay"]["id"], "response_minutes": 60})
            assert r.status_code == 422 and r.json()["detail"]["code"] == "no_account"
            break
    # un manager sans le droit de modifier ne lance rien
    assert o.post("/users", json={"email": f"aud@{t['dom']}", "name": "Aud", "role": "auditor", "password": PW}).status_code == 201
    aud = login(f"aud@{t['dom']}")
    a = sched(o, pid)[0]
    assert aud.post(f"/shifts/{a['shift_id']}/replacement-requests", json={"start_employee_id": emps["ana"]["id"], "response_minutes": 60}).status_code == 403
    from app.replacements import MIN_LEAD
    assert MIN_LEAD == timedelta(minutes=5)  # en deçà du début du shift : plus de proposition (choix direct par le manager)


def test_version_officielle_inchangee_jusqu_a_la_publication(t):
    """Planning validé : l'acceptation modifie le planning en cours, jamais la version validée ; le changement est signalé et le
    collaborateur est informé que le planning publié sera mis à jour à la prochaine publication."""
    o, pid, users, by_id = t["o"], t["pid"], t["users"], t["by_id"]
    v = max(o.get(f"/periods/{pid}/versions").json(), key=lambda x: x["number"])
    o.post(f"/versions/{v['id']}/submit")
    assert o.post(f"/versions/{v['id']}/validate").status_code == 200
    from app.db import tenant_session
    from app import models as m
    tid = o.get("/auth/me").json()["tenant_id"]

    def official():
        with tenant_session(tid) as db:
            x = db.get(m.ScheduleVersion, uuid.UUID(v["id"]))
            return x.state, x.snapshot
    snap_before = official()
    assert snap_before[0] == "validated" and snap_before[1]
    a, cands = pick(t)
    launch(o, a["shift_id"], cands[0])
    c = users[by_id[cands[0]]]
    oid = c.get("/me/replacement-offers").json()["items"][0]["id"]
    r = c.post(f"/replacement-offers/{oid}/accept")
    assert r.status_code == 200 and "mis à jour à la prochaine publication" in r.json()["message"]
    assert official() == snap_before  # la version validée n'est jamais modifiée (état et contenu)
    p = next(x for x in o.get("/periods").json() if x["id"] == pid)
    assert p["changed_since"] is True  # « modifié depuis la validation » : à republier par le circuit habituel
    assert any("publiez une nouvelle version" in n["body"] for n in notes(o, "replacement_update"))


def test_suppression_du_planning_proposition_invalidee_et_retiree_de_mon_espace(t):
    """Planning supprimé pendant une proposition : la proposition devient « plus valable » (collaborateur prévenu), elle n'apparaît plus
    dans « Mon espace » et ne peut pas être acceptée ; elle reste en base (historique)."""
    o, pid, users, by_id = t["o"], t["pid"], t["users"], t["by_id"]
    a, cands = pick(t)
    req = launch(o, a["shift_id"], cands[0])
    c1 = users[by_id[cands[0]]]
    oid = c1.get("/me/replacement-offers").json()["items"][0]["id"]
    assert o.post(f"/periods/{pid}/delete", json={"password": PW}).status_code == 200
    assert c1.get("/me/replacement-offers").json()["items"] == []
    assert any("planning de ce mois a été supprimé" in n["body"] for n in notes(c1, "replacement_cancelled"))
    r = c1.post(f"/replacement-offers/{oid}/accept")
    assert r.status_code in (404, 409), r.text
    from app.db import tenant_session
    with tenant_session(o.get("/auth/me").json()["tenant_id"]) as db:
        st = db.execute(text("SELECT r.status, o.status FROM replacement_requests r JOIN replacement_offers o ON o.request_id = r.id WHERE r.id = :r"),
                        {"r": req["id"]}).one()
    assert tuple(st) == ("invalidated", "invalidated")
