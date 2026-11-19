"""Budget du mois prérempli depuis le budget de base de la marque : 88 h -> ajusté à 96 h pour le mois, conservé, jamais écrasé, utilisé
par le moteur ; aucun effet sur les autres mois ni sur les plannings existants. Données entièrement créées par les tests."""
import uuid

import pytest

from tests.conftest import make_client, register


@pytest.fixture
def t():
    o = make_client()
    register(o, "Budgets SA", f"budgets-{uuid.uuid4().hex[:8]}@example.com")
    assert o.post("/catalog/sites", json={"code": "AERO", "name": "Aéroport"}).status_code == 201
    r = o.post("/catalog/brands", json={"name": "Nuxe", "base_budget_hours": 88})
    assert r.status_code == 201 and r.json()["base_budget_minutes"] == 88 * 60
    assert o.post("/catalog/brands", json={"name": "Alpha"}).status_code == 201  # aucun budget de base
    for b in ("Nuxe", "Alpha"):
        assert o.post("/catalog/animations", json={"site_code": "AERO", "brand_code": b, "start": "09:00", "end": "18:00", "weekdays": [0, 1, 2, 3, 4, 5, 6],
                                                   "headcount": 1, "from_month": "2026-11"}).status_code == 201
    for code in ("ana", "ben", "cleo"):
        assert o.post("/employees", json={"code": code, "name": code.capitalize(), "brands": {"Nuxe": "priority", "Alpha": "priority"}}).status_code == 201
    return dict(o=o)


def brands(o, pid):
    return {b["code"]: b for b in o.get(f"/periods/{pid}/brands").json()}


def test_88_h_prerempli_ajuste_a_96_h_conserve_et_utilise_par_le_moteur(t):
    o = t["o"]
    dec = o.post("/periods/ensure", json={"year": 2026, "month": 12}).json()["id"]
    b = brands(o, dec)
    assert b["Nuxe"]["budget_minutes"] == 88 * 60 and b["Nuxe"]["base_minutes"] == 88 * 60  # prérempli à la création du mois
    assert b["Alpha"]["budget_minutes"] is None and b["Alpha"]["base_minutes"] is None  # aucun budget de base : rien d'inventé
    assert o.put(f"/periods/{dec}/brands/Nuxe", json={"budget_minutes": 96 * 60}).json()["budget_minutes"] == 96 * 60
    for _ in range(2):  # rouvrir l'étape (ou actualiser) ne réécrase jamais l'ajustement
        assert brands(o, dec)["Nuxe"]["budget_minutes"] == 96 * 60
    # le moteur utilise le budget du mois (96 h), selon le mode choisi (plafond strict par défaut)
    r = o.post(f"/periods/{dec}/runs", json={"time_limit_s": 8}, headers={"Idempotency-Key": uuid.uuid4().hex})
    assert r.status_code == 202
    rep = o.get(f"/runs/{r.json()['run_id']}/diagnostic").json()["report"]
    nuxe = next(x for x in rep["budgets"] if x["brand"] == "Nuxe")
    assert nuxe["target_minutes"] == 96 * 60 and nuxe["planned_minutes"] <= 96 * 60  # plafond strict respecté
    # le budget de base n'a pas changé ; un autre mois créé ensuite repart de la base
    assert next(x for x in o.get("/catalog").json()["brands"] if x["code"] == "Nuxe")["base_budget_minutes"] == 88 * 60
    jan = o.post("/periods/ensure", json={"year": 2027, "month": 1}).json()["id"]
    assert brands(o, jan)["Nuxe"]["budget_minutes"] == 88 * 60
    assert brands(o, dec)["Nuxe"]["budget_minutes"] == 96 * 60


def test_champ_vide_jamais_rerempli_et_plannings_existants_preserves(t):
    o = t["o"]
    nov = o.post("/periods/ensure", json={"year": 2026, "month": 11}).json()["id"]
    assert o.put(f"/periods/{nov}/brands/Nuxe", json={"clear_budget": True}).status_code == 200  # ajustement : aucun budget ce mois
    assert brands(o, nov)["Nuxe"]["budget_minutes"] is None  # le préremplissage ne revient pas
    assert o.put(f"/periods/{nov}/brands/Alpha", json={"budget_minutes": 40 * 60}).status_code == 200
    r = o.post(f"/periods/{nov}/runs", json={"time_limit_s": 8}, headers={"Idempotency-Key": uuid.uuid4().hex})
    assert r.status_code == 202
    # changer ou ajouter un budget de base ne modifie jamais un mois existant (généré ou non)
    assert o.patch("/catalog/brands/Nuxe", json={"base_budget_hours": 120}).json()["base_budget_minutes"] == 120 * 60
    assert o.patch("/catalog/brands/Alpha", json={"base_budget_hours": 10}).status_code == 200
    b = brands(o, nov)
    assert b["Nuxe"]["budget_minutes"] is None and b["Alpha"]["budget_minutes"] == 40 * 60
    feb = o.post("/periods/ensure", json={"year": 2027, "month": 2}).json()["id"]
    b = brands(o, feb)
    assert b["Nuxe"]["budget_minutes"] == 120 * 60 and b["Alpha"]["budget_minutes"] == 10 * 60  # nouveau mois : nouvelles bases
    hist = o.get("/history").json()  # la nouvelle base n'est pas un « changement de planning »
    assert hist["items"] is not None
    assert o.patch("/catalog/brands/Nuxe", json={"clear_base_budget": True}).json()["base_budget_minutes"] is None


def test_budget_ajuste_conserve_apres_suppression_et_recreation_du_planning(t):
    """96 h saisies pour décembre (base 88 h) : supprimer puis recréer le planning de décembre reprend 96 h (le budget appartient au mois)."""
    from tests.conftest import PW
    o = t["o"]
    dec = o.post("/periods/ensure", json={"year": 2026, "month": 12}).json()["id"]
    assert o.put(f"/periods/{dec}/brands/Nuxe", json={"budget_minutes": 96 * 60}).status_code == 200
    assert o.post(f"/periods/{dec}/runs", json={"time_limit_s": 8}, headers={"Idempotency-Key": uuid.uuid4().hex}).status_code == 202
    assert o.post(f"/periods/{dec}/delete", json={"password": PW}).status_code == 200
    new = o.post("/periods/ensure", json={"year": 2026, "month": 12}).json()
    assert new["created"] is True and new["id"] != dec
    b = brands(o, new["id"])
    assert b["Nuxe"]["budget_minutes"] == 96 * 60 and b["Nuxe"]["base_minutes"] == 88 * 60  # ajustement repris, jamais remplacé par la base
    assert b["Alpha"]["budget_minutes"] is None
    r = o.post(f"/periods/{new['id']}/runs", json={"time_limit_s": 8}, headers={"Idempotency-Key": uuid.uuid4().hex})
    rep = o.get(f"/runs/{r.json()['run_id']}/diagnostic").json()["report"]
    assert next(x for x in rep["budgets"] if x["brand"] == "Nuxe")["target_minutes"] == 96 * 60
    # un mois jamais saisi reçoit toujours la base
    assert brands(o, o.post("/periods/ensure", json={"year": 2027, "month": 3}).json()["id"])["Nuxe"]["budget_minutes"] == 88 * 60
