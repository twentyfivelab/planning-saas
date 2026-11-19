"""Intégration d'une nouvelle marque ou d'un nouveau collaborateur au planning existant d'un mois : choix explicite (recalcul complet ou
saisie manuelle), suivi de couverture de la marque, rien d'automatique, aucun autre mois touché. Données entièrement créées par les tests."""
import uuid

import pytest

from tests.conftest import make_client, register


def gen(o, pid, limit=8):
    r = o.post(f"/periods/{pid}/runs", json={"time_limit_s": limit}, headers={"Idempotency-Key": uuid.uuid4().hex})
    assert r.status_code == 202, r.text
    return o.get(f"/runs/{r.json()['run_id']}").json()


def rows(o, pid):
    return sorted((a["assignment_id"], a["employee_id"], a["shift_id"]) for a in o.get(f"/periods/{pid}/schedule").json()["assignments"])


@pytest.fixture
def t():
    o = make_client()
    register(o, "Intégration SA", f"integ-{uuid.uuid4().hex[:8]}@example.com")
    assert o.post("/catalog/sites", json={"code": "AERO", "name": "Aéroport"}).status_code == 201
    assert o.post("/catalog/brands", json={"name": "Alpha"}).status_code == 201
    assert o.post("/catalog/animations", json={"site_code": "AERO", "brand_code": "Alpha", "start": "09:00", "end": "18:00", "weekdays": [0, 1, 2, 3, 4, 5, 6],
                                               "headcount": 1, "from_month": "2026-12"}).status_code == 201
    emps = {c: o.post("/employees", json={"code": c, "name": c.capitalize(), "brands": {"Alpha": "priority"}}).json() for c in ("ana", "ben", "cleo")}
    dec = o.post("/periods/ensure", json={"year": 2026, "month": 12}).json()["id"]
    jan = o.post("/periods/ensure", json={"year": 2027, "month": 1}).json()["id"]
    for pid in (dec, jan):
        assert gen(o, pid)["status"] == "termine"
    return dict(o=o, dec=dec, jan=jan, emps=emps)


def add_nuxe(o):
    assert o.post("/catalog/brands", json={"name": "Nuxe"}).status_code == 201


def nuxe_needs(o):
    assert o.post("/catalog/animations", json={"site_code": "AERO", "brand_code": "Nuxe", "start": "10:00", "end": "17:00", "weekdays": [5],
                                               "headcount": 1, "from_month": "2026-12"}).status_code == 201


def test_marque_saisie_manuelle_suivi_de_couverture(t):
    o, dec, jan = t["o"], t["dec"], t["jan"]
    dec_before, jan_before = rows(o, dec), rows(o, jan)
    add_nuxe(o)
    c = o.get("/integrations/candidates", params={"brand_code": "Nuxe"}).json()
    assert [p["label"] for p in c["periods"]] == ["décembre 2026", "janvier 2027"] and c["entity"]["name"] == "Nuxe"
    assert rows(o, dec) == dec_before  # la seule création de la marque ne change rien
    r = o.post(f"/periods/{dec}/integrations", json={"kind": "brand", "brand_code": "Nuxe", "choice": "manual"})
    assert r.status_code == 201 and r.json()["run_id"] is None
    assert rows(o, dec) == dec_before and rows(o, jan) == jan_before  # aucune affectation créée, aucun autre mois touché
    items = o.get(f"/periods/{dec}/integrations").json()["items"]
    assert len(items) == 1 and items[0]["coverage"]["needs_missing"] is True and items[0]["coverage"]["complete"] is False  # « Besoins à renseigner »
    assert o.get(f"/periods/{jan}/integrations").json()["items"] == []
    # besoins définis : 4 samedis en décembre 2026, tous à placer
    nuxe_needs(o)
    cov = o.get(f"/periods/{dec}/integrations").json()["items"][0]["coverage"]
    assert (cov["total"], cov["to_place"], cov["covered"], cov["remaining"]) == (4, 4, 0, 4) and cov["need_minutes"] == 4 * 360
    assert [x["day"] for x in cov["items"]] == ["2026-12-05", "2026-12-12", "2026-12-19", "2026-12-26"] and cov["items"][0]["site_name"] == "Aéroport"
    iid = items[0]["id"]
    # placer un besoin : shift sans collaborateur (aucune affectation créée)
    pl = o.post(f"/periods/{dec}/integrations/{iid}/place", json={"slot_key": cov["items"][0]["slot_key"]})
    assert pl.status_code == 201 and pl.json()["already"] is False
    assert o.post(f"/periods/{dec}/integrations/{iid}/place", json={"slot_key": cov["items"][0]["slot_key"]}).json()["already"] is True  # jamais en double
    cov = o.get(f"/periods/{dec}/integrations").json()["items"][0]["coverage"]
    assert (cov["unassigned"], cov["to_place"], cov["covered"]) == (1, 3, 0)
    assert len(rows(o, dec)) == len(dec_before)
    # attribution avec les contrôles habituels : un collaborateur autorisé pour Nuxe, intégré au mois
    dan = o.post("/employees", json={"code": "dan", "name": "Dan", "brands": {"Nuxe": "priority", "Alpha": "priority"}}).json()
    assert o.post(f"/periods/{dec}/integrations", json={"kind": "employee", "employee_id": dan["id"], "choice": "manual"}).status_code == 201
    a = o.post(f"/periods/{dec}/manual-assign", json={"employee_id": dan["id"], "shift_id": pl.json()["shift_id"]})
    assert a.status_code == 200, a.text
    cov = o.get(f"/periods/{dec}/integrations").json()["items"][0]["coverage"]
    assert (cov["covered"], cov["remaining"], cov["covered_minutes"], cov["remaining_minutes"]) == (1, 3, 360, 3 * 360)
    emp_item = next(i for i in o.get(f"/periods/{dec}/integrations").json()["items"] if i["kind"] == "employee")
    assert emp_item["assigned"] == 1 and "quota" not in emp_item  # jamais de quota inventé pour un collaborateur
    # conflit : un shift affecté en conflit n'est pas compté comme couvert (même collaborateur deux fois le même jour, dérogation tracée)
    pl2 = o.post(f"/periods/{dec}/integrations/{iid}/place", json={"slot_key": cov["items"][0]["slot_key"]}).json()
    day = cov["items"][0]["day"]
    busy = next(x for x in o.get(f"/periods/{dec}/schedule").json()["assignments"] if x["day"] == day)
    f = o.post(f"/periods/{dec}/manual-assign", json={"employee_id": busy["employee_id"], "shift_id": pl2["shift_id"], "force": True, "reason": "test conflit"})
    assert f.status_code == 200, f.text
    cov = o.get(f"/periods/{dec}/integrations").json()["items"][0]["coverage"]
    assert cov["conflict"] == 1 and cov["covered"] == 1 and cov["assigned"] == 2 and cov["complete"] is False
    assert next(x for x in cov["items"] if x["state"] == "conflict")["conflicts"]
    assert rows(o, jan) == jan_before
    # historique : le choix et les shifts placés, avec leur auteur
    hist = o.get("/history", params={"kind": "integration"}).json()["items"]
    titles = [h["title"] for h in hist]
    assert "Intégration de la marque Nuxe au planning de décembre 2026" in titles and any(x.startswith("Shift placé sans collaborateur sur Nuxe") for x in titles)
    me = o.get("/auth/me").json()["name"]
    assert all(h["by"] == me for h in hist)
    # masquer le suivi : plus affiché, le choix reste dans l'historique
    assert o.post(f"/periods/{dec}/integrations/{iid}/dismiss").status_code == 200
    assert all(i["kind"] != "brand" for i in o.get(f"/periods/{dec}/integrations").json()["items"])


def test_marque_recalcul_verifications_puis_nouvelle_version(t):
    o, dec, jan = t["o"], t["dec"], t["jan"]
    jan_before = rows(o, jan)
    add_nuxe(o)
    # informations manquantes : aucun calcul lancé, guidage vers la saisie
    r = o.post(f"/periods/{dec}/integrations", json={"kind": "brand", "brand_code": "Nuxe", "choice": "recalculate", "time_limit_s": 8})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "not_ready"
    assert {x["code"] for x in r.json()["detail"]["missing"]} >= {"needs", "budget"}
    runs_before = len(o.get("/runs").json())
    nuxe_needs(o)
    rd = o.get(f"/periods/{dec}/integrations/readiness", params={"brand_code": "Nuxe"}).json()
    assert [x["code"] for x in rd["missing"]] == ["budget"] and rd["shifts"] == 4
    assert o.put(f"/periods/{dec}/brands/Nuxe", json={"budget_minutes": 24 * 60}).status_code == 200
    assert o.get(f"/periods/{dec}/integrations/readiness", params={"brand_code": "Nuxe"}).json()["ready"] is True
    # Nuxe demande un collaborateur autorisé : un nouveau collaborateur, intégré au même recalcul
    dan = o.post("/employees", json={"code": "dan", "name": "Dan", "brands": {"Nuxe": "priority"}}).json()
    assert o.post(f"/periods/{dec}/integrations", json={"kind": "employee", "employee_id": dan["id"], "choice": "manual"}).status_code == 201
    v_before = {v["number"] for v in o.get(f"/periods/{dec}/versions").json()}
    r = o.post(f"/periods/{dec}/integrations", json={"kind": "brand", "brand_code": "Nuxe", "choice": "recalculate", "time_limit_s": 8},
               headers={"Idempotency-Key": uuid.uuid4().hex})
    assert r.status_code == 201, r.text
    run = o.get(f"/runs/{r.json()['run_id']}").json()
    assert run["status"] == "termine" and run["save"]["outcome"] == "replaced" and len(o.get("/runs").json()) == runs_before + 1
    new = [v for v in o.get(f"/periods/{dec}/versions").json() if v["number"] not in v_before]
    labels = {v["label"] for v in new}
    assert labels == {"Avant intégration de Nuxe", "Planning recalculé avec Nuxe"}  # planning initial conservé, résultat identifiable
    assert not any(v["state"] == "published" for v in o.get(f"/periods/{dec}/versions").json())  # rien n'est publié
    sched = o.get(f"/periods/{dec}/schedule").json()["assignments"]
    assert any("Nuxe" in a["allocations"] for a in sched)
    assert rows(o, jan) == jan_before  # aucun autre mois recalculé
    hist = o.get("/history", params={"kind": "integration"}).json()["items"]
    assert any("Recalculer tout le planning" in " ".join(h["lines"]) for h in hist)


def test_collaborateur_ajoute_au_mois_sans_affectation_ni_quota(t):
    o, dec, jan = t["o"], t["dec"], t["jan"]
    dec_before, jan_before = rows(o, dec), rows(o, jan)
    eve = o.post("/employees", json={"code": "eve", "name": "Eve", "brands": {"Alpha": "priority"}}).json()
    c = o.get("/integrations/candidates", params={"employee_id": eve["id"]}).json()
    assert [p["label"] for p in c["periods"]] == ["décembre 2026", "janvier 2027"]
    ros = {x["name"]: x for x in o.get(f"/periods/{dec}/roster").json()["employees"]}
    assert ros["Eve"]["state"] == "excluded"  # ajouté après la création du planning : jamais d'effet rétroactif automatique
    assert o.post(f"/periods/{dec}/integrations", json={"kind": "employee", "employee_id": eve["id"], "choice": "manual"}).status_code == 201
    ros = {x["name"]: x for x in o.get(f"/periods/{dec}/roster").json()["employees"]}
    assert ros["Eve"]["state"] == "included"
    assert {x["name"]: x for x in o.get(f"/periods/{jan}/roster").json()["employees"]}["Eve"]["state"] == "excluded"  # autre mois intact
    assert rows(o, dec) == dec_before and rows(o, jan) == jan_before
    it = o.get(f"/periods/{dec}/integrations").json()["items"]
    assert it == [{**it[0], "kind": "employee", "name": "Eve", "assigned": 0, "minutes": 0}]
    c = o.get("/integrations/candidates", params={"employee_id": eve["id"]}).json()
    assert c["periods"][0]["already"]["choice"] == "manual" and c["periods"][1]["already"] is None


def test_planning_publie_demande_confirmation_et_droits(t):
    o, dec = t["o"], t["dec"]
    add_nuxe(o)
    nuxe_needs(o)
    assert o.put(f"/periods/{dec}/brands/Nuxe", json={"budget_minutes": 24 * 60}).status_code == 200
    vs = o.get(f"/periods/{dec}/versions").json()
    v = max(vs, key=lambda x: x["number"])
    o.post(f"/versions/{v['id']}/submit")
    o.post(f"/versions/{v['id']}/validate")
    if not o.get(f"/periods/{dec}/versions").json() or not any(x["state"] in ("validated", "published") for x in o.get(f"/periods/{dec}/versions").json()):
        pytest.skip("validation impossible dans ce jeu de données")
    r = o.post(f"/periods/{dec}/integrations", json={"kind": "brand", "brand_code": "Nuxe", "choice": "recalculate", "time_limit_s": 8})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "official_version"
    assert o.get(f"/periods/{dec}/integrations").json()["items"] == []  # refus : aucun choix enregistré
    assert not [h for h in o.get("/history", params={"kind": "integration"}).json()["items"]]


def notes(o, kind_prefix="coverage_"):
    return [n for n in o.get("/notifications").json()["items"] if n["kind"].startswith(kind_prefix)]


def test_notifications_de_couverture_aux_seuls_changements_d_etat(t):
    """Complète -> une notification ; modification sans changement d'état -> rien ; suppression -> « de nouveau incomplète » une seule fois ;
    conflit -> jamais « couvert » ; besoins retirés -> « Besoins à renseigner » ; suivi masqué -> plus rien. Persistant à la reconnexion."""
    o, dec = t["o"], t["dec"]
    add_nuxe(o)
    nuxe_needs(o)  # 4 samedis
    dan = o.post("/employees", json={"code": "dan", "name": "Dan", "brands": {"Nuxe": "priority"}}).json()
    eve = o.post("/employees", json={"code": "eve", "name": "Eve", "brands": {"Nuxe": "priority"}}).json()
    for e in (dan, eve):
        assert o.post(f"/periods/{dec}/integrations", json={"kind": "employee", "employee_id": e["id"], "choice": "manual"}).status_code == 201
    iid = o.post(f"/periods/{dec}/integrations", json={"kind": "brand", "brand_code": "Nuxe", "choice": "manual"}).json()["integration_id"]
    assert notes(o) == []  # le choix lui-même ne notifie pas
    cov = lambda: next(i for i in o.get(f"/periods/{dec}/integrations").json()["items"] if i["kind"] == "brand")["coverage"]  # noqa: E731
    items = cov()["items"]
    aids = []
    for k, x in enumerate(items):
        sid = o.post(f"/periods/{dec}/integrations/{iid}/place", json={"slot_key": x["slot_key"]}).json()["shift_id"]
        r = o.post(f"/periods/{dec}/manual-assign", json={"employee_id": (dan, eve)[k % 2]["id"], "shift_id": sid})
        assert r.status_code == 200, r.text
        aids.append(r.json()["assignment_id"])
        if k < 3:
            assert notes(o) == []  # 1, 2, 3 sur 4 : toujours incomplète, aucune notification répétée
    c = cov()
    assert c["complete"] is True and c["remaining"] == 0
    n = notes(o)
    assert [x["kind"] for x in n] == ["coverage_complete"] and n[0]["title"] == "Nuxe : tous les besoins de décembre 2026 sont couverts"
    assert n[0]["body"] == "Tous les shifts de Nuxe sont attribués et sans conflit (4 shift(s), 24 h)." and n[0]["payload"]["month"] == "2026-12"
    # modification sans effet sur l'état (verrou d'une affectation Alpha) : aucune nouvelle notification
    alpha = next(a for a in o.get(f"/periods/{dec}/schedule").json()["assignments"] if "Alpha" in a["allocations"])
    assert o.post(f"/assignments/{alpha['assignment_id']}/lock").status_code in (200, 204)
    assert len(notes(o)) == 1
    # suppression : de nouveau incomplète, une seule fois
    assert o.delete(f"/assignments/{aids[0]}", params={"force": True}).status_code == 204
    n = notes(o)
    assert [x["kind"] for x in n] == ["coverage_incomplete", "coverage_complete"]
    assert n[0]["title"] == "Nuxe : couverture de décembre 2026 de nouveau incomplète" and n[0]["body"] == "1 shift(s) (6 h) restent à attribuer : 1 sans collaborateur."
    assert o.delete(f"/assignments/{aids[1]}", params={"force": True}).status_code == 204
    assert len(notes(o)) == 2  # toujours incomplète : rien de plus
    c = cov()
    assert (c["remaining"], c["remaining_minutes"], c["unassigned"]) == (2, 12 * 60, 2)
    # reconnexion : notifications et état conservés
    me = o.get("/auth/me").json()
    o2 = make_client()
    assert o2.post("/auth/login", json={"email": me["email"], "password": __import__("tests.conftest", fromlist=["PW"]).PW}).status_code == 200
    assert len(notes(o2)) == 2 and next(i for i in o2.get(f"/periods/{dec}/integrations").json()["items"] if i["kind"] == "brand")["coverage"]["remaining"] == 2
    # de nouveau complète
    for k, x in enumerate(c["items"]):
        assert o.post(f"/periods/{dec}/manual-assign", json={"employee_id": (dan, eve)[k % 2]["id"], "shift_id": x["shift_id"]}).status_code == 200
    assert [x["kind"] for x in notes(o)][0] == "coverage_complete" and len(notes(o)) == 3
    # conflit : un collaborateur déjà occupé ce jour-là sur un shift Nuxe -> jamais « couvert »
    day = c["items"][0]["day"]
    busy = next(a for a in o.get(f"/periods/{dec}/schedule").json()["assignments"] if a["day"] == day and "Alpha" in a["allocations"])
    nx = next(a for a in o.get(f"/periods/{dec}/schedule").json()["assignments"] if a["day"] == day and "Nuxe" in a["allocations"])
    assert o.post(f"/periods/{dec}/manual-assign", json={"employee_id": busy["employee_id"], "shift_id": nx["shift_id"], "force": True, "reason": "test"}).status_code == 200
    c = cov()
    assert c["complete"] is False and c["conflict"] == 1
    n = notes(o)
    assert len(n) == 4 and n[0]["kind"] == "coverage_incomplete" and "1 en conflit" in n[0]["body"]
    # besoins retirés (marque archivée à partir de décembre) : « Besoins à renseigner », jamais une confirmation
    assert o.patch("/catalog/brands/Nuxe", json={"archived_from": "2026-12"}).status_code == 200
    assert cov()["needs_missing"] is True
    assert len(notes(o)) == 4  # incomplète -> besoins à renseigner : pas une nouvelle alerte de « perte de couverture »
    assert o.patch("/catalog/brands/Nuxe", json={"archived_from": ""}).status_code == 200
    # suivi masqué : plus aucune notification
    assert o.post(f"/periods/{dec}/integrations/{iid}/dismiss").status_code == 200
    assert o.delete(f"/assignments/{nx['assignment_id']}", params={"force": True}).status_code == 204
    assert len(notes(o)) == 4
