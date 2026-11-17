"""Règles de planning : portée des relations, absences partielles, horaires obligatoires, temps de déplacement entre sites, pauses sans
relève sur les sites à présence continue. Données entièrement créées par les tests."""
import uuid

import pytest

from tests.conftest import make_client, register

OCT, NOV = (2026, 10), (2026, 11)


def build():
    o = make_client()
    register(o, "Règles SA", f"regles-{uuid.uuid4().hex[:8]}@example.com")
    for code, name in (("AERO", "Aéroport"), ("GARE", "Gare")):
        assert o.post("/catalog/sites", json={"code": code, "name": name}).status_code == 201
    assert o.post("/catalog/brands", json={"name": "Alpha"}).status_code == 201
    for site in ("AERO", "GARE"):
        r = o.post("/catalog/animations", json={"site_code": site, "brand_code": "Alpha", "start": "09:00", "end": "18:00", "weekdays": [0, 1, 2, 3, 4, 5, 6],
                                                "headcount": 1, "from_month": "2026-10"})
        assert r.status_code == 201, r.text
    emps = {}
    for code in ("ana", "ben", "cleo", "dan"):
        r = o.post("/employees", json={"code": code, "name": code.capitalize(), "brands": {"Alpha": "priority"}})
        assert r.status_code == 201, r.text
        emps[code] = r.json()
    pids = {ym: o.post("/periods/ensure", json={"year": ym[0], "month": ym[1]}).json()["id"] for ym in (OCT, NOV)}
    return o, emps, pids


def run(o, pid, **body):
    r = o.post(f"/periods/{pid}/runs", json={"time_limit_s": 8, **body}, headers={"Idempotency-Key": uuid.uuid4().hex})
    assert r.status_code == 202, r.text
    res = o.get(f"/runs/{r.json()['run_id']}").json()
    assert res["status"] == "termine", res
    return res


def rows(o, pid):
    return o.get(f"/periods/{pid}/schedule").json()["assignments"]


@pytest.fixture
def t():
    o, emps, pids = build()
    return dict(o=o, emps=emps, pids=pids)


def test_absence_partielle_generation_controle_manuel_et_planning_individuel(t):
    o, emps, pid = t["o"], t["emps"], t["pids"][NOV]
    ana = emps["ana"]["id"]
    assert o.post("/partial-absences", json={"employee_id": ana, "on_date": "2026-11-10", "start_time": "12:00", "end_time": "10:00"}).status_code == 422
    r = o.post("/partial-absences", json={"employee_id": ana, "on_date": "2026-11-10", "start_time": "10:00", "end_time": "12:00", "reason": "rendez-vous"})
    assert r.status_code == 201, r.text
    run(o, pid)
    a = rows(o, pid)
    assert not [x for x in a if x["employee_id"] == ana and x["day"] == "2026-11-10"]  # tous les shifts de ce jour chevauchent l'absence
    target = next(x for x in a if x["day"] == "2026-11-10")
    r = o.post(f"/periods/{pid}/manual-assign", json={"employee_id": ana, "shift_id": target["shift_id"]})
    assert r.status_code == 409
    issue = next(i for i in r.json()["detail"]["issues"] if i["code"] == "UNAVAILABLE_PARTIAL")
    assert issue["level"] == "override" and "10:00" in issue["message"] and "12:00" in issue["message"]
    month = o.get(f"/employees/{ana}/month?month=2026-11").json()
    day = next(d for d in month["days"] if d["date"] == "2026-11-10")
    assert day["partial"] == [{"start": "10:00", "end": "12:00", "reason": "rendez-vous"}] and day["off"] is None  # le jour reste travaillable


def test_horaires_obligatoires_et_independance_des_plannings_existants(t):
    o, emps, pids = t["o"], t["emps"], t["pids"]
    ben = emps["ben"]["id"]
    run(o, pids[NOV])  # novembre conservé SANS horaires obligatoires
    before = sorted((x["slot_key"], x["employee_id"]) for x in rows(o, pids[NOV]))
    assert any(x["employee_id"] == ben for x in rows(o, pids[NOV]))
    assert o.post("/employee-preferences", json={"employee_id": ben, "kind": "work_window", "params": {"start": "18:00", "end": "10:00"}}).status_code == 422
    r = o.post("/employee-preferences", json={"employee_id": ben, "kind": "work_window", "params": {"start": "10:00", "end": "20:00"}})
    assert r.status_code == 201 and r.json()["is_hard"] is True  # toujours une contrainte dure
    run(o, pids[OCT])  # octobre généré APRÈS : les shifts 9 h – 18 h sont hors de ses horaires
    assert not [x for x in rows(o, pids[OCT]) if x["employee_id"] == ben]
    # novembre : rien ne change, aucune incompatibilité, la différence est seulement signalée
    assert o.get(f"/periods/{pids[NOV]}/compatibility").json()["compatible"] is True
    diffs = o.get(f"/periods/{pids[NOV]}/params").json()["differences"]
    d = next(x for x in diffs if x["field"] == "work_window")
    assert (d["planning"], d["current"]) == ("Pas de préférence", "10:00–20:00")
    run(o, pids[NOV])  # nouvelle génération avec les paramètres conservés : Ben reste planifiable de 9 h à 18 h
    assert any(x["employee_id"] == ben for x in rows(o, pids[NOV]))
    assert len(rows(o, pids[NOV])) == len(before)


def test_relation_a_separer_meme_jour_tous_sites(t):
    o, emps, pid = t["o"], t["emps"], t["pids"][NOV]
    ana, ben = emps["ana"]["id"], emps["ben"]["id"]
    bad = o.post("/relationship-preferences", json={"employee_id": ana, "other_employee_id": ben, "kind": "work_together", "scope": "day"})
    assert bad.status_code == 422
    r = o.post("/relationship-preferences", json={"employee_id": ana, "other_employee_id": ben, "kind": "avoid_together", "strict": True, "scope": "day"})
    assert r.status_code == 201 and r.json()["scope"] == "day"
    run(o, pid)
    a = rows(o, pid)
    days = lambda eid: {x["day"] for x in a if x["employee_id"] == eid}  # noqa: E731
    assert days(ana) and days(ben) and not days(ana) & days(ben)  # jamais le même jour, même sur deux sites différents
    # le contrôle d'une modification manuelle applique la même règle
    on_ana_day = next(x for x in a if x["employee_id"] not in (ana, ben) and x["day"] in days(ana))
    r = o.post(f"/periods/{pid}/manual-assign", json={"employee_id": ben, "shift_id": on_ana_day["shift_id"]})
    assert r.status_code == 409 and any(i["code"] == "RELATION_AVOID" for i in r.json()["detail"]["issues"])


def test_temps_de_deplacement_valide_et_conserve_par_planning(t):
    o, pids = t["o"], t["pids"]
    run(o, pids[NOV])  # planning conservé avant la règle
    assert o.post("/site-travel", json={"from_site": "AERO", "to_site": "AERO", "minutes": 20}).status_code == 422
    assert o.post("/site-travel", json={"from_site": "AERO", "to_site": "LUNE", "minutes": 20}).status_code == 422
    assert o.post("/site-travel", json={"from_site": "AERO", "to_site": "GARE", "minutes": 40}).status_code == 201
    d = next(x for x in o.get(f"/periods/{pids[NOV]}/params").json()["differences"] if x["field"] == "travel_minutes")
    assert (d["planning"], d["current"]) == ("Aucun temps de déplacement", "AERO ↔ GARE : 40 min")
    run(o, pids[OCT])
    assert o.get(f"/periods/{pids[OCT]}/params").json()["differences"] == []  # octobre a conservé la règle en vigueur à sa création


def test_pause_sans_releve_sur_site_a_presence_continue(t):
    o, pid = t["o"], t["pids"][NOV]
    run(o, pid)
    assert o.get(f"/periods/{pid}/break-coverage").json() == {"sites": [], "items": []}
    site = next(s for s in o.get("/sites").json() if s["code"] == "AERO")
    assert o.put(f"/sites/{site['id']}", json={"code": "AERO", "name": "Aéroport", "continuous_presence": True}).status_code == 200
    assert o.put(f"/sites/{site['id']}", json={"code": "AERO", "name": "Aéroport T1"}).status_code == 200  # écran sans ce champ : valeur conservée
    assert next(s for s in o.get("/sites").json() if s["code"] == "AERO")["continuous_presence"] is True
    rep = o.get(f"/periods/{pid}/break-coverage").json()
    on_site = [x for x in rows(o, pid) if x["site"] == "AERO"]
    assert rep["sites"] == ["AERO"] and len(rep["items"]) == len(on_site) > 0  # une seule personne par jour : aucune relève possible
    assert "sans relève possible" in rep["items"][0]["message"]


def _post_confirmed(o, url, body):
    """Envoie l'opération ; si des alertes dérogeables sont listées, confirme comme le ferait l'écran (rôle propriétaire)."""
    r = o.post(url, json=body)
    if r.status_code == 409 and r.json()["detail"]["code"] == "needs_confirmation":
        r = o.post(url, json={**body, "force": True, "reason": "test"})
    return r


def test_echange_reciproque_meme_jour_sans_fausse_double_affectation(t):
    o, pid = t["o"], t["pids"][NOV]
    run(o, pid)
    a = rows(o, pid)
    day = next(d for d in sorted({x["day"] for x in a}) if len({x["site"] for x in a if x["day"] == d}) == 2)
    A, B = [x for x in a if x["day"] == day][:2]  # deux sites, deux collaborateurs, le même jour
    assert A["employee_id"] != B["employee_id"]
    r = o.post(f"/periods/{pid}/swap", json={"a": A["assignment_id"], "b": A["assignment_id"]})
    assert r.status_code == 404
    r = _post_confirmed(o, f"/periods/{pid}/swap", {"a": A["assignment_id"], "b": B["assignment_id"]})
    assert r.status_code == 200, r.text
    after = {x["assignment_id"]: x for x in rows(o, pid)}
    assert after[A["assignment_id"]]["employee_id"] == B["employee_id"] and after[B["assignment_id"]]["employee_id"] == A["employee_id"]
    assert after[A["assignment_id"]]["locked"] and after[B["assignment_id"]]["locked"]
    assert o.get(f"/periods/{pid}/regularizations").json() == []  # chacun garde un seul shift ce jour-là
    assert len(after) == len(a)  # aucun shift créé ni perdu


def test_echange_controle_par_les_memes_regles(t):
    o, pid = t["o"], t["pids"][NOV]
    run(o, pid)
    a = rows(o, pid)
    by = {}
    for x in a:
        by.setdefault(x["employee_id"], []).append(x)
    e1, e2 = list(by)[:2]
    B = next(x for x in by[e2] if x["day"] not in {y["day"] for y in by[e1]})
    A = next(x for x in by[e1] if x["day"] not in {y["day"] for y in by[e2]})
    # le collaborateur 1 a une absence partielle le jour du shift qu'il recevrait
    assert o.post("/partial-absences", json={"employee_id": e1, "on_date": B["day"], "start_time": "08:00", "end_time": "10:00"}).status_code == 201
    r = o.post(f"/periods/{pid}/swap", json={"a": A["assignment_id"], "b": B["assignment_id"]})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "needs_confirmation"
    assert any(i["code"] == "UNAVAILABLE_PARTIAL" for i in r.json()["detail"]["issues"])
    assert sorted((x["assignment_id"], x["employee_id"]) for x in rows(o, pid)) == sorted((x["assignment_id"], x["employee_id"]) for x in a)  # rien changé


def test_duplication_controlee_jour_par_jour_et_retirable(t):
    o, pid = t["o"], t["pids"][NOV]
    run(o, pid)
    a = rows(o, pid)
    src = a[0]
    eid = src["employee_id"]
    mine = {x["day"] for x in a if x["employee_id"] == eid}
    free = [d for d in (f"2026-11-{k:02d}" for k in range(1, 31)) if d not in mine][:2]
    assert o.post(f"/assignments/{src['assignment_id']}/duplicate", json={"days": ["2026-12-01"]}).status_code == 422
    assert o.post(f"/assignments/{src['assignment_id']}/duplicate", json={"days": [src["day"]]}).status_code == 422
    assert o.post("/partial-absences", json={"employee_id": eid, "on_date": free[1], "start_time": "17:00", "end_time": "19:00"}).status_code == 201
    r = o.post(f"/assignments/{src['assignment_id']}/duplicate", json={"days": free})
    assert r.status_code == 409
    issues = r.json()["detail"]["issues"]
    hit = next(i for i in issues if i["code"] == "UNAVAILABLE_PARTIAL")
    assert hit["day"] == free[1] and hit["message"].startswith(f"{free[1][8:]}/11")
    assert len(rows(o, pid)) == len(a)  # tout ou rien : aucune copie
    r = o.post(f"/assignments/{src['assignment_id']}/duplicate", json={"days": free, "force": True, "reason": "renfort"})
    assert r.status_code == 200, r.text
    created = r.json()["created"]
    now = rows(o, pid)
    copies = [x for x in now if x["assignment_id"] in {c["assignment_id"] for c in created}]
    assert sorted(x["day"] for x in copies) == free
    assert all((x["start"], x["end"], x["site"], x["employee_id"], x["allocations"]) == (src["start"], src["end"], src["site"], eid, src["allocations"]) for x in copies)
    assert o.delete(f"/assignments/{created[0]['assignment_id']}?force=true").status_code == 204  # copie retirable, son shift disparaît
    assert len(rows(o, pid)) == len(a) + 1
