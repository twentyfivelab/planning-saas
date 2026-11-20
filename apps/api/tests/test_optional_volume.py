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
    up = _volume_report(inp, ["a"], ["a", "b"])  # une hausse est signalée aussi, avec sa raison
    assert up["delta_optional"] == 1 and "1 shift(s) optionnel(s) de plus" in up["note"] and "cible commune" in up["note"]


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


def test_resultat_en_six_blocs(t):
    o, pid, run = t["o"], t["pid"], t["run"]
    s = o.get(f"/runs/{run['id']}/summary").json()
    b = s["blocks"]
    assert list(b) == ["rules", "coverage", "budgets", "fairness", "remaining", "optimisation"]
    assert b["rules"]["state"] == "ok" and b["rules"]["checked"] > 0 and "contrôle indépendant" in b["rules"]["text"]
    assert b["coverage"]["state"] == "ok" and b["coverage"]["mandatory"] == b["coverage"]["covered"] == 23
    assert b["budgets"]["state"] == "info" and "Aucun budget saisi" in b["budgets"]["text"]  # aucun budget : dit, jamais supposé
    assert b["fairness"]["spread"] is not None and len(b["fairness"]["employees"]) == 3 and all(e["target_minutes"] > 0 for e in b["fairness"]["employees"])
    opt = o.get(f"/periods/{pid}/optional-needs").json()
    assert b["remaining"]["optional_unassigned"] == opt["total"]
    assert b["optimisation"]["proved"] in (True, False)
    if not b["optimisation"]["proved"]:
        assert "Planning valide et utilisable, mais optimisation non terminée" in b["optimisation"]["text"]
    assert "ancienneté" in s["priorities"][-1] and any(p.startswith("Équité des heures (niveau propre") for p in s["priorities"])
    assert any("un seul niveau" in p for p in s["priorities"])  # différence du mode à un seul niveau dite explicitement


def test_bilan_d_equite_toutes_les_heures_et_nature_des_cibles(t):
    """Bilan d'équité : TOUTES les heures attribuées (y compris les besoins optionnels sans budget, comptés à part), cible calculée sur le
    volume décidé (mode hiérarchisé), atteinte de chaque cible ; en mode à un seul niveau, cible « estimée » et différence expliquée."""
    o, pid, run = t["o"], t["pid"], t["run"]
    rows = o.get(f"/periods/{pid}/schedule").json()["assignments"]
    f = o.get(f"/runs/{run['id']}/summary").json()["blocks"]["fairness"]
    assert f["total_minutes"] == sum(a["effective_minutes"] for a in rows)
    assert f["unbudgeted_minutes"] == sum(a["effective_minutes"] for a in rows if "Valmont" in a["allocations"])  # optionnel sans budget
    assert sum(e["minutes"] for e in f["employees"]) == f["total_minutes"]
    assert sum(e["unbudgeted_minutes"] for e in f["employees"]) == f["unbudgeted_minutes"]
    assert f["basis"] == "volume décidé" and f["mode"] == "hiérarchisé" and "Bilan sur toutes les heures attribuées" in f["text"]
    assert all(e["target_status"] in ("atteinte", "optimum prouvé", "non démontrée") for e in f["employees"])
    assert all(e["deviation_minutes"] == e["minutes"] - e["target_minutes"] for e in f["employees"])
    assert "repos minimal entre deux shifts" in f["flow_not_represented"] and "partage des shifts entre collègues" in f["flow_represents"]
    # mode à un seul niveau (option des pondérations) : cible estimée, équité mise en balance avec les préférences
    assert o.put("/settings/weights", json={"hierarchical": False}).status_code == 200
    try:
        r = o.post(f"/periods/{pid}/runs", json={"time_limit_s": 8, "params": "current"}, headers={"Idempotency-Key": uuid.uuid4().hex})
        run2 = o.get(f"/runs/{r.json()['run_id']}").json()
        f2 = o.get(f"/runs/{run2['id']}/summary").json()["blocks"]["fairness"]
        assert f2["basis"] == "estimée" and f2["mode"] == "un seul niveau" and "Cible ESTIMÉE" in f2["text"]
        assert all(e["target_status"] in ("estimée", "aucun shift possible") for e in f2["employees"])
    finally:
        assert o.put("/settings/weights", json={"hierarchical": True}).status_code == 200


def test_modification_pendant_la_generation_jamais_ecrasee(t, monkeypatch):
    """Lot 3 (20/11/2026, démontré par la mesure à plusieurs managers) : une réaffectation faite PENDANT une génération du même mois était
    écrasée sans avertissement à l'enregistrement du résultat. Désormais elle est conservée : le résultat n'est pas enregistré, la
    raison est donnée (« modifié pendant le calcul »), et aucune version n'est créée."""
    import app.optimize as opt
    o, pid, emps = t["o"], t["pid"], t["emps"]
    real = opt.solve
    rows = o.get(f"/periods/{pid}/schedule").json()["assignments"]
    a = next(x for x in rows if not x["locked"])
    busy = {x["employee_id"] for x in rows if x["day"] == a["day"]}
    to = next(e for e in emps.values() if e["id"] not in busy)
    versions = len(o.get(f"/periods/{pid}/versions").json())

    def edited_during_search(inp, cancel=None, on_progress=None):
        res = real(inp, cancel, on_progress)
        r = o.put(f"/assignments/{a['assignment_id']}", json={"employee_id": to["id"], "expected_employee_id": a["employee_id"]})
        assert r.status_code == 200, r.text  # un manager modifie le planning pendant le calcul
        return res
    monkeypatch.setattr(opt, "solve", edited_during_search)
    r = o.post(f"/periods/{pid}/runs", json={"time_limit_s": 8, "confirm_replace": True}, headers={"Idempotency-Key": uuid.uuid4().hex})
    run = o.get(f"/runs/{r.json()['run_id']}").json()
    assert run["save"]["outcome"] == "kept_previous" and run["save"]["reason_code"] == "modified_during_run", run["save"]
    assert "pour ne pas écraser ces modifications" in run["save"]["reason"] and run["save"]["changes"] >= 1
    now = next(x for x in o.get(f"/periods/{pid}/schedule").json()["assignments"] if x["assignment_id"] == a["assignment_id"])
    assert now["employee_id"] == to["id"]  # la modification du manager est conservée
    assert len(o.get(f"/periods/{pid}/versions").json()) == versions
    s = o.get(f"/runs/{run['id']}/summary").json()["blocks"]["optimisation"]
    assert "modifié pendant le calcul" in s["text"]
