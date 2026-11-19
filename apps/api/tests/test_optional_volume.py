"""Volume attribué présenté à part de l'équité (toute baisse des shifts optionnels visible et expliquée), besoins optionnels non attribués
listés et complétables à la main, distinction « planning valide » / « optimum prouvé ». Données entièrement créées par les tests."""
import uuid
from datetime import date, time
from types import SimpleNamespace

import pytest

from tests.conftest import make_client, register


@pytest.fixture
def t():
    o = make_client()
    register(o, "Volume SA", f"vol-{uuid.uuid4().hex[:8]}@example.com")
    assert o.post("/catalog/sites", json={"code": "AERO", "name": "Aéroport"}).status_code == 201
    for b in ("Ploom", "Valmont"):
        assert o.post("/catalog/brands", json={"name": b}).status_code == 201
    assert o.post("/catalog/animations", json={"site_code": "AERO", "brand_code": "Ploom", "start": "09:00", "end": "18:00", "weekdays": [0, 1, 2, 3, 4],
                                               "headcount": 1, "from_month": "2026-12"}).status_code == 201
    assert o.post("/catalog/animations", json={"site_code": "AERO", "brand_code": "Valmont", "start": "10:00", "end": "19:00", "weekdays": [5],
                                               "headcount": 1, "mandatory": False, "from_month": "2026-12"}).status_code == 201  # optionnel, sans budget
    emps = {c: o.post("/employees", json={"code": c, "name": c.capitalize(), "brands": {"Ploom": "priority", "Valmont": "priority"}}).json() for c in ("ana", "ben", "cleo")}
    pid = o.post("/periods/ensure", json={"year": 2026, "month": 12}).json()["id"]
    r = o.post(f"/periods/{pid}/runs", json={"time_limit_s": 8}, headers={"Idempotency-Key": uuid.uuid4().hex})
    assert r.status_code == 202
    return dict(o=o, pid=pid, emps=emps, run=o.get(f"/runs/{r.json()['run_id']}").json())


def test_volume_et_preuve_dans_le_resultat(t):
    run = t["run"]
    assert run["status"] == "termine" and run["save"]["outcome"] == "replaced"
    v = run["save"]["volume"]
    assert v["after"]["mandatory"] == 23  # jours ouvrés de décembre 2026 (besoins Ploom obligatoires)
    assert v["optional_without_budget"] == ["Valmont"] and v["note"] is None  # premier calcul : rien à comparer
    assert run["proof"]["proved"] in (True, False) and run["proof"]["levels"] and run["proof"]["time_limit_s"] == 8


def test_baisse_des_optionnels_visible_et_expliquee():
    from app.optimize import _volume_report
    s = lambda sid, mand, brand: SimpleNamespace(id=sid, mandatory=mand, effective_minutes=480, brands={brand: 1}, allocations={brand: 480})  # noqa: E731
    inp = SimpleNamespace(slots=[s("a", True, "Ploom"), s("b", False, "Valmont"), s("c", False, "Valmont"), s("d", False, "Nuxe")],
                          budgets=[SimpleNamespace(brand="Nuxe")])
    r = _volume_report(inp, ["a", "b", "c", "d"], ["a", "d"])
    assert (r["before"]["optional"], r["after"]["optional"], r["delta_optional"], r["delta_optional_minutes"]) == (3, 1, -2, -960)
    assert r["optional_without_budget"] == ["Valmont"] and "2 shift(s) optionnel(s) de moins" in r["note"] and "16 h" in r["note"] and "Valmont" in r["note"]
    assert _volume_report(inp, ["a"], ["a", "b"])["note"] is None  # une hausse n'est pas une baisse à signaler


def test_besoins_optionnels_listes_places_puis_attribues(t):
    o, pid, emps = t["o"], t["pid"], t["emps"]
    d = o.get(f"/periods/{pid}/optional-needs").json()
    sat = 4  # samedis de décembre 2026
    assigned_opt = t["run"]["save"]["volume"]["after"]["optional"]
    assert d["total"] == sat - assigned_opt and d["minutes"] == d["total"] * 480
    if not d["total"]:
        pytest.skip("le moteur a retenu tous les besoins optionnels")
    assert d["brands"][0]["brand"] == "Valmont" and d["brands"][0]["budget_minutes"] is None
    n = d["items"][0]
    before = len(o.get(f"/periods/{pid}/schedule").json()["assignments"])
    pl = o.post(f"/periods/{pid}/needs/place", json={"slot_key": n["slot_key"]})
    assert pl.status_code == 201 and pl.json()["already"] is False
    assert o.post(f"/periods/{pid}/needs/place", json={"slot_key": n["slot_key"]}).json()["already"] is True  # jamais en double
    assert len(o.get(f"/periods/{pid}/schedule").json()["assignments"]) == before  # aucune affectation créée par le placement
    assert next(x for x in o.get(f"/periods/{pid}/optional-needs").json()["items"] if x["slot_key"] == n["slot_key"])["placed"] is True
    free = next(e for e in emps.values() if not any(a["day"] == n["day"] and a["employee_id"] == e["id"] for a in o.get(f"/periods/{pid}/schedule").json()["assignments"]))
    r = o.post(f"/periods/{pid}/manual-assign", json={"employee_id": free["id"], "shift_id": pl.json()["shift_id"], "force": True, "reason": "complément optionnel"})
    assert r.status_code == 200, r.text
    assert all(x["slot_key"] != n["slot_key"] for x in o.get(f"/periods/{pid}/optional-needs").json()["items"])
    h = o.get("/history", params={"kind": "add"}).json()["items"]
    assert any(x["title"].startswith("Besoin optionnel placé sans collaborateur") for x in h)
    assert o.post(f"/periods/{pid}/needs/place", json={"slot_key": "inconnu"}).status_code == 422
    assert date(2026, 12, 5).weekday() == 5 and time(10)  # repères de l'énoncé (samedis)


def test_annulation_pendant_le_calcul_n_enregistre_jamais_la_solution(t, monkeypatch):
    """Annulation demandée PENDANT la recherche (le moteur rend une solution) : rien n'est enregistré, le planning initial reste
    intact et la raison est « Calcul annulé ». (Défaut trouvé le 19/11 par le test navigateur : la solution partielle était enregistrée.)"""
    import app.optimize as opt
    o, pid = t["o"], t["pid"]
    before = sorted((a["assignment_id"], a["employee_id"]) for a in o.get(f"/periods/{pid}/schedule").json()["assignments"])
    versions = len(o.get(f"/periods/{pid}/versions").json())
    real = opt.solve

    def cancelled_during_search(inp, cancel=None, on_progress=None):
        res = real(inp, cancel, on_progress)
        cancel.set()  # l'utilisateur annule au moment où le moteur rend sa solution
        return res
    monkeypatch.setattr(opt, "solve", cancelled_during_search)
    r = o.post(f"/periods/{pid}/runs", json={"time_limit_s": 8}, headers={"Idempotency-Key": uuid.uuid4().hex})
    run = o.get(f"/runs/{r.json()['run_id']}").json()
    assert run["status"] == "annule" and run["save"]["outcome"] == "kept_previous" and run["save"]["reason_code"] == "cancelled", run["save"]
    assert sorted((a["assignment_id"], a["employee_id"]) for a in o.get(f"/periods/{pid}/schedule").json()["assignments"]) == before
    assert len(o.get(f"/periods/{pid}/versions").json()) == versions  # aucune version « avant / après » créée
