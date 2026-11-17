"""Fiche d'ajout et suppression des collaborateurs, plafond mensuel d'heures, jours minimum / maximum par mois, paramètres conservés
par chaque planning, détail des incompatibilités et suivi du calcul. Données entièrement créées par les tests."""
import uuid

import pytest

from tests.conftest import make_client, register

OCT, NOV = (2026, 10), (2026, 11)


def build():
    o = make_client()
    register(o, "Equipe SA", f"team-{uuid.uuid4().hex[:8]}@example.com")
    assert o.post("/catalog/sites", json={"code": "AERO", "name": "Aéroport"}).status_code == 201
    assert o.post("/catalog/brands", json={"name": "Alpha"}).status_code == 201
    r = o.post("/catalog/animations", json={"site_code": "AERO", "brand_code": "Alpha", "start": "09:00", "end": "18:00", "weekdays": [0, 1, 2, 3, 4, 5, 6],
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


def sched(o, pid):
    return sorted((a["slot_key"], a["employee_id"]) for a in o.get(f"/periods/{pid}/schedule").json()["assignments"])


@pytest.fixture
def t():
    o, emps, pids = build()
    return dict(o=o, emps=emps, pids=pids)


def test_fiche_d_ajout_complete_et_message(t):
    o = t["o"]
    body = {"first_name": "Léa", "last_name": "MARTIN", "birth_date": "1994-03-12", "address_street": "Rue du Rhône 1", "address_postal_code": "1204",
            "address_city": "Genève", "address_country": "Suisse", "phone": "+41 79 123 45 67", "email": "lea.martin@example.com", "monthly_hours": 120,
            "weekly_hours": 28, "brands": {"Alpha": "priority"}, "sites": ["AERO"], "available_weekdays": [0, 1, 2, 3, 4], "unavailable_weekdays": [],
            "unavailable_dates": ["2026-10-14"], "time_pref": "matin", "time_pref_strict": False, "min_days_month": 5, "max_days_month": 18}
    r = o.post("/employees/onboard", json=body)
    assert r.status_code == 201, r.text
    assert r.json()["message"] == "Le collaborateur Léa MARTIN a été ajouté avec succès."
    e = next(x for x in o.get("/employees").json() if x["id"] == r.json()["id"])
    assert (e["name"], e["first_name"], e["last_name"], e["address_city"], e["phone"], e["min_days_month"], e["max_days_month"]) == (
        "Léa MARTIN", "Léa", "MARTIN", "Genève", "+41 79 123 45 67", 5, 18)
    c = next(x for x in o.get("/contracts").json() if x["employee_id"] == e["id"])
    assert (c["monthly_target_minutes"], c["weekly_minutes"]) == (7200, 1680)
    assert sorted(a["weekday"] for a in o.get("/availabilities").json() if a["employee_id"] == e["id"]) == [0, 1, 2, 3, 4]
    assert o.get(f"/employees/{e['id']}/availability").json()["dates"] == ["2026-10-14"]
    pref = next(p for p in o.get("/employee-preferences").json() if p["employee_id"] == e["id"])
    assert (pref["kind"], pref["is_hard"], pref["params"]) == ("sites", True, {"sites": ["AERO"]})


def test_doublons_verifies_avant_l_ajout(t):
    o = t["o"]
    base = {"first_name": "Noé", "last_name": "BLANC", "email": "noe@example.com", "phone": "079 555 66 77", "brands": {"Alpha": "priority"}}
    assert o.post("/employees/onboard", json=base).status_code == 201
    n = len(o.get("/employees").json())
    r = o.post("/employees/onboard", json={**base, "first_name": "Autre", "last_name": "NOM", "phone": None})  # même e-mail : refusé
    assert r.status_code == 409 and r.json()["detail"]["code"] == "duplicate" and r.json()["detail"]["can_confirm"] is False
    assert "même adresse e-mail" in r.json()["detail"]["matches"][0]["reasons"]
    r = o.post("/employees/onboard", json={**base, "email": None, "first_name": "Zoé", "phone": "+41 79 555 66 77"})  # même téléphone
    assert r.status_code == 409 and not r.json()["detail"]["can_confirm"]
    r = o.post("/employees/onboard", json={**base, "email": None, "phone": None})  # homonyme : confirmation demandée
    assert r.status_code == 409 and r.json()["detail"]["can_confirm"] is True
    assert len(o.get("/employees").json()) == n  # rien n'a été créé
    assert o.post("/employees/onboard", json={**base, "email": None, "phone": None, "confirm_duplicate": True}).status_code == 201
    r = o.post("/employees/onboard", json={"first_name": "Ana", "last_name": "DUPONT", "brands": {}})  # fiche existante au seul prénom « Ana »
    assert r.status_code == 409 and "seul prénom" in r.json()["detail"]["matches"][0]["reasons"][0]


def test_parametres_incoherents_expliques(t):
    o = t["o"]
    ok = {"first_name": "Ivo", "last_name": "ROSSI", "brands": {"Alpha": "priority"}}
    r = o.post("/employees/onboard", json={**ok, "min_days_month": 20, "max_days_month": 10})
    assert r.status_code == 422 and "Le minimum (20 jours) dépasse le maximum (10 jours)" in r.json()["detail"]
    r = o.post("/employees/onboard", json={**ok, "min_days_month": 25})  # shifts de 8 h : 25 jours = 200 h > 176 h
    assert r.status_code == 422 and "Minimum possible : 22 jours" in r.json()["detail"] and "176 h" in r.json()["detail"]
    r = o.post("/employees/onboard", json={**ok, "monthly_hours": 180})
    assert r.status_code == 422 and "dépasse le plafond mensuel de 176 h" in r.json()["detail"]
    r = o.post("/employees/onboard", json={**ok, "available_weekdays": [0], "unavailable_weekdays": [0]})
    assert r.status_code == 422 and "à la fois disponible et indisponible" in r.json()["detail"]
    ana = t["emps"]["ana"]
    r = o.put(f"/employees/{ana['id']}", json={"code": "ana", "name": "Ana", "min_days_month": 23})
    assert r.status_code == 422 and "Minimum possible : 22 jours" in r.json()["detail"]
    r = o.put(f"/employees/{ana['id']}/month-params/2026-11", json={"days_set": True, "min_days": 12, "max_days": 10})
    assert r.status_code == 422 and "dépasse le maximum" in r.json()["detail"]


def test_suppression_conserve_l_historique_et_retire_des_prochains_plannings(t):
    o, pids = t["o"], t["pids"]
    run(o, pids[OCT])
    before = sched(o, pids[OCT])
    ana = t["emps"]["ana"]
    assert any(e == ana["id"] for _k, e in before)
    prev = o.get(f"/employees/{ana['id']}/deletion-preview").json()
    assert prev["name"] == "Ana"
    r = o.delete(f"/employees/{ana['id']}")
    assert r.status_code == 200 and r.json()["message"] == "Le collaborateur Ana a été supprimé avec succès."
    assert o.delete(f"/employees/{ana['id']}").status_code == 409
    assert ana["id"] not in {e["id"] for e in o.get("/employees").json()}
    assert ana["id"] in {e["id"] for e in o.get("/employees?include_deleted=true").json()}
    assert sched(o, pids[OCT]) == before  # affectations et historique conservés
    assert not [i for i in o.get(f"/periods/{pids[OCT]}/compatibility").json()["items"] if i["code"] == "EMPLOYEE_REMOVED"]  # octobre : avant le retrait
    run(o, pids[NOV])
    assert ana["id"] not in {e for _k, e in sched(o, pids[NOV])}  # plus jamais planifié
    sh = o.get(f"/periods/{pids[NOV]}/schedule").json()["assignments"][0]
    r = o.put(f"/assignments/{sh['assignment_id']}", json={"employee_id": ana["id"]})
    assert r.status_code in (409, 422)
    r = o.post(f"/employees/{ana['id']}/restore")
    assert r.status_code == 200 and r.json()["message"] == "Le collaborateur Ana a été réintégré."
    assert ana["id"] in {e["id"] for e in o.get("/employees").json()}


def test_chaque_planning_conserve_ses_parametres(t):
    o, pids, ben = t["o"], t["pids"], t["emps"]["ben"]
    run(o, pids[OCT])
    oct_plan = sched(o, pids[OCT])
    oct_compat = o.get(f"/periods/{pids[OCT]}/compatibility").json()
    assert o.get(f"/periods/{pids[OCT]}/params").json()["frozen"] is True
    assert any(e == ben["id"] for _k, e in oct_plan)
    # changement fait pour les prochains mois : Ben n'est plus autorisé sur Alpha
    assert o.put(f"/employees/{ben['id']}", json={"code": "ben", "name": "Ben", "brands": {}}).status_code == 200
    assert o.get(f"/periods/{pids[OCT]}/compatibility").json()["items"] == oct_compat["items"]  # aucune nouvelle incompatibilité en octobre
    preview = o.get(f"/periods/{pids[OCT]}/compatibility?params=current").json()
    assert any(i["code"] == "BRAND_NOT_ELIGIBLE" and i["employee"] == "Ben" and i["kind"] == "obligatoire" and i["shifts"] for i in preview["items"])
    diffs = o.get(f"/periods/{pids[OCT]}/params").json()["differences"]
    assert any(d["employee"] == "Ben" and d["field"] == "brands" for d in diffs)
    impact = o.get(f"/employees/{ben['id']}/impact").json()["periods"]
    row = next(p for p in impact if p["period_id"] == pids[OCT])
    assert row["frozen"] and row["hard"] == 0 and row["if_applied"]["hard"] > 0
    # générer novembre ne touche pas octobre
    run(o, pids[NOV])
    assert sched(o, pids[OCT]) == oct_plan
    assert o.get(f"/periods/{pids[OCT]}/compatibility").json()["items"] == oct_compat["items"]
    assert ben["id"] not in {e for _k, e in sched(o, pids[NOV])}  # novembre : paramètres actuels (planning sans paramètres conservés)
    # appliquer les paramètres actuels : action explicite, aucune affectation modifiée
    assert o.post(f"/periods/{pids[OCT]}/params/apply-current", json={}).status_code == 422
    r = o.post(f"/periods/{pids[OCT]}/params/apply-current", json={"confirm": True})
    assert r.status_code == 200 and any(i["code"] == "BRAND_NOT_ELIGIBLE" for i in r.json()["items"])
    assert sched(o, pids[OCT]) == oct_plan
    assert o.get(f"/periods/{pids[OCT]}/params").json()["differences"] == []


def test_generation_avec_les_parametres_du_planning_ou_actuels(t):
    o, pids, cleo = t["o"], t["pids"], t["emps"]["cleo"]
    run(o, pids[OCT])
    assert o.put(f"/employees/{cleo['id']}", json={"code": "cleo", "name": "Cleo", "brands": {}}).status_code == 200
    res = run(o, pids[OCT])  # par défaut : paramètres conservés par le planning
    rep = o.get(f"/runs/{res['id']}/diagnostic").json()["report"]
    assert rep["params_used"]["mode"] == "frozen" and rep["params_used"]["monthly_cap_minutes"] == 10560
    assert cleo["id"] in {e for _k, e in sched(o, pids[OCT])}
    assert res["progress"] and res["progress"]["phase"] in ("saving", "checking", "level")
    res = run(o, pids[OCT], params="current")  # choix explicite
    assert o.get(f"/runs/{res['id']}/diagnostic").json()["report"]["params_used"]["mode"] == "current"
    assert cleo["id"] not in {e for _k, e in sched(o, pids[OCT])}
    assert o.get(f"/periods/{pids[OCT]}/params").json()["differences"] == []


def test_plafond_mensuel_en_generation_et_en_modification_manuelle(t):
    o, pids = t["o"], t["pids"]
    assert o.get("/settings/monthly-cap").json()["minutes"] == 10560
    assert o.put("/settings/monthly-cap", json={"hours": 16}).status_code == 200  # 2 shifts de 8 h par mois et par collaborateur
    run(o, pids[OCT])
    per = {}
    for a in o.get(f"/periods/{pids[OCT]}/schedule").json()["assignments"]:
        per[a["employee_id"]] = per.get(a["employee_id"], 0) + a["effective_minutes"]
    assert per and max(per.values()) <= 960
    full = next(eid for eid, m in per.items() if m == 960)
    free = next(u for u in o.get(f"/periods/{pids[OCT]}/schedule").json()["uncovered"])
    r = o.post(f"/periods/{pids[OCT]}/manual-assign", json={"employee_id": full, "shift_id": free["shift_id"], "force": True})
    assert r.status_code == 409 and any(i["code"] == "MONTHLY_CAP" and i["level"] == "blocking" for i in r.json()["detail"]["issues"])
    tpl = next(x for x in o.get("/brand-schedules").json()["Alpha"])
    r = o.post(f"/periods/{pids[OCT]}/assignments", json={"employee_id": full, "day": free["day"], "brand_code": "Alpha", "template_id": tpl["template_id"]})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "monthly_cap" and "plafond mensuel de 16 h" in r.json()["detail"]["message"]
    assert sum(a["effective_minutes"] for a in o.get(f"/periods/{pids[OCT]}/schedule").json()["assignments"] if a["employee_id"] == full) == 960
    assert o.put("/settings/monthly-cap", json={"hours": 176}).status_code == 200


def test_exception_du_mois_sur_les_jours(t):
    o, pids, dan = t["o"], t["pids"], t["emps"]["dan"]
    r = o.put(f"/employees/{dan['id']}/month-params/2026-10", json={"days_set": True, "min_days": 3, "max_days": 4})
    assert r.status_code == 200 and (r.json()["days_set"], r.json()["min_days"], r.json()["max_days"]) == (True, 3, 4)
    run(o, pids[OCT])
    days = {k.split("|")[1] for k, e in sched(o, pids[OCT]) if e == dan["id"]}
    assert 3 <= len(days) <= 4
    nov = o.get("/month-params?month=2026-11").json()
    assert next(x for x in nov if x["employee_id"] == dan["id"])["days_set"] is False  # les autres mois ne changent pas


def test_suppression_sans_incompatibilite_retroactive_et_plus_jamais_planifie(t):
    """Planning existant : les affectations d'un collaborateur supprimé restent (historique), signalées sans être des incompatibilités ;
    une nouvelle génération ne lui attribue plus aucun shift à partir de sa date de retrait."""
    o, pids, ben = t["o"], t["pids"], t["emps"]["ben"]
    run(o, pids[NOV])
    assert o.delete(f"/employees/{ben['id']}").status_code == 200
    rows = o.get(f"/periods/{pids[NOV]}/schedule").json()["assignments"]
    removed_on = next(e for e in o.get("/employees?include_deleted=true").json() if e["id"] == ben["id"])["removed_on"]
    late = [a for a in rows if a["employee_id"] == ben["id"] and a["day"] >= removed_on]
    comp = o.get(f"/periods/{pids[NOV]}/compatibility").json()
    assert not [i for i in comp["items"] if i["code"] == "EMPLOYEE_REMOVED"]  # aucune incompatibilité rétroactive
    if late:
        assert comp["removed_notice"] == [{"employee": "Ben", "removed_on": removed_on, "assignments": len(late)}]
    run(o, pids[NOV])  # nouvelle génération (paramètres du planning) : Ben n'est plus planifié après son retrait
    assert not [a for a in o.get(f"/periods/{pids[NOV]}/schedule").json()["assignments"] if a["employee_id"] == ben["id"] and a["day"] >= removed_on]
    assert o.post(f"/employees/{ben['id']}/restore").status_code == 200


def test_ponderations_conservees_avec_le_planning(t):
    o, pids = t["o"], t["pids"]
    first = run(o, pids[OCT])
    used = o.get(f"/runs/{first['id']}/diagnostic").json()["report"]["weights_used"]
    pp = o.get(f"/periods/{pids[OCT]}/params").json()
    assert pp["weights"] == used and pp["generation_run_id"] == first["id"]  # conditions de génération retrouvables
    assert o.put("/settings/weights", json={"criteria": {"fairness": 20}}).status_code == 200
    assert any(d["field"] == "weights" for d in o.get(f"/periods/{pids[OCT]}/params").json()["differences"])
    again = run(o, pids[OCT])  # paramètres du planning : pondérations de sa génération
    assert o.get(f"/runs/{again['id']}/diagnostic").json()["report"]["weights_used"]["fairness"] == used["fairness"]
    cur = run(o, pids[OCT], params="current")  # choix explicite : nouvelles pondérations
    assert o.get(f"/runs/{cur['id']}/diagnostic").json()["report"]["weights_used"]["fairness"] < used["fairness"]
    o.post("/settings/weights/reset")


def test_minimum_de_jours_obligatoire_et_blocage_explique(t):
    o, pids, emps = t["o"], t["pids"], t["emps"]
    for code in ("ana", "ben"):  # 2 x 20 jours pour 31 shifts : chacun possible, pas les deux
        r = o.put(f"/employees/{emps[code]['id']}/month-params/2026-10", json={"days_set": True, "min_days": 20})
        assert r.status_code == 200, r.text
    run(o, pids[OCT], params="current")
    before = sched(o, pids[OCT])
    r = o.post(f"/periods/{pids[OCT]}/runs", json={"time_limit_s": 8}, headers={"Idempotency-Key": uuid.uuid4().hex})
    res = o.get(f"/runs/{r.json()['run_id']}").json()
    assert res["result_status"] == "infaisable"
    diag = o.get(f"/runs/{res['id']}/diagnostic").json()["report"]["diagnostics"]
    msg = next(i["message"] for i in diag if i["code"] == "MIN_DAYS_CONFLICT")
    assert "Ana (20 jours en octobre 2026)" in msg and "Ben (20 jours en octobre 2026)" in msg
    assert sched(o, pids[OCT]) == before  # rien n'est enregistré
    o.put(f"/employees/{emps['ben']['id']}/month-params/2026-10", json={"days_set": False})
    res = run(o, pids[OCT])
    days = {k.split("|")[1] for k, e in sched(o, pids[OCT]) if e == emps["ana"]["id"]}
    assert len(days) >= 20  # minimum respecté
    # minimum impossible à lui seul : signalé avant la génération
    assert o.put(f"/employees/{emps['cleo']['id']}", json={"code": "cleo", "name": "Cleo", "brands": {}}).status_code == 200
    o.put(f"/employees/{emps['cleo']['id']}/month-params/2026-11", json={"days_set": True, "min_days": 5})
    ready = o.get(f"/periods/{pids[NOV]}/readiness").json()
    assert any(i["level"] == "blocking" and "Minimum de jours impossible pour Cleo" in i["text"] for i in ready["issues"])


def test_reduire_un_depassement_reste_possible(t):
    o, pids = t["o"], t["pids"]
    assert o.put("/settings/monthly-cap", json={"hours": 16}).status_code == 200
    run(o, pids[OCT])
    assert o.put("/settings/monthly-cap", json={"hours": 8}).status_code == 200  # tous au-delà du nouveau plafond
    rows = o.get(f"/periods/{pids[OCT]}/schedule").json()["assignments"]
    a, b = rows[0], next(x for x in rows if x["employee_id"] != rows[0]["employee_id"])
    r = o.put(f"/assignments/{a['assignment_id']}", json={"employee_id": b["employee_id"]})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "monthly_cap"  # aggraverait le dépassement de B
    r = o.patch(f"/shifts/{a['shift_id']}", json={"start_time": "09:00:00", "end_time": "13:00:00", "break_minutes": 0})
    assert r.status_code == 200, r.text  # réduit les heures de A : permis
    assert o.put("/settings/monthly-cap", json={"hours": 176}).status_code == 200


def test_reoptimisation_locale_d_un_planning_qui_depasse_deja_le_plafond(t):
    """Planning établi avant un plafond plus bas : une réoptimisation locale reste possible, sans jamais aggraver un dépassement."""
    o, pids = t["o"], t["pids"]
    run(o, pids[OCT])
    rows = o.get(f"/periods/{pids[OCT]}/schedule").json()["assignments"]
    per = {}
    for a in rows:
        per[a["employee_id"]] = per.get(a["employee_id"], 0) + a["effective_minutes"]
    assert o.put("/settings/monthly-cap", json={"hours": 40}).status_code == 200  # tous au-delà de 40 h
    target = rows[0]
    r = o.post(f"/periods/{pids[OCT]}/local-reoptimize", json={"employee_id": target["employee_id"], "start": target["day"], "end": target["day"], "time_limit_s": 8})
    assert r.status_code in (200, 202), r.text
    res = o.get(f"/runs/{r.json()['run_id']}").json()
    assert res["status"] == "termine", res
    rep = o.get(f"/runs/{res['id']}/diagnostic").json()["report"]
    assert not rep["hard_violations"] and rep.get("proposal"), rep.get("hard_violations")
    applied = o.post(f"/simulations/{res['id']}/apply", json={})
    assert applied.status_code == 200, applied.text  # le dépassement antérieur n'empêche pas l'application
    after = {}
    for a in o.get(f"/periods/{pids[OCT]}/schedule").json()["assignments"]:
        after[a["employee_id"]] = after.get(a["employee_id"], 0) + a["effective_minutes"]
    assert all(after.get(e, 0) <= max(per[e], 40 * 60) for e in after)  # aucun dépassement aggravé
    assert o.put("/settings/monthly-cap", json={"hours": 176}).status_code == 200


def test_collaborateur_ajoute_apres_un_planning_ne_le_modifie_pas(t):
    o, pids = t["o"], t["pids"]
    run(o, pids[OCT])
    before = o.get(f"/periods/{pids[OCT]}/compatibility").json()["items"]
    r = o.post("/employees/onboard", json={"first_name": "Nora", "last_name": "NOUVELLE", "brands": {"Alpha": "priority"}, "min_days_month": 5})
    assert r.status_code == 201, r.text
    assert o.get(f"/periods/{pids[OCT]}/compatibility").json()["items"] == before  # pas d'incompatibilité rétroactive (minimum de 5 jours)
    roster = o.get(f"/periods/{pids[OCT]}/roster").json()
    row = next(x for x in (roster["employees"] if isinstance(roster, dict) else roster) if x["name"] == "Nora NOUVELLE")
    assert row["state"] == "excluded" and row["reason"] == "Ajouté après la création de ce planning"
    assert any(d["field"] == "new" and d["employee"] == "Nora NOUVELLE" for d in o.get(f"/periods/{pids[OCT]}/params").json()["differences"])
    run(o, pids[OCT])  # paramètres du planning : Nora n'en fait pas partie
    assert r.json()["id"] not in {e for _k, e in sched(o, pids[OCT])}
    # inclusion explicite dans l'effectif d'octobre : elle est alors planifiée avec ses paramètres
    assert o.put(f"/periods/{pids[OCT]}/roster", json={"employees": [{"employee_id": r.json()["id"], "included": True}]}).status_code == 200
    run(o, pids[OCT])
    assert len({k.split("|")[1] for k, e in sched(o, pids[OCT]) if e == r.json()["id"]}) >= 5


def test_chaque_version_fige_son_contexte_et_sa_conformite(t):
    """Chaque version garde SES données de génération (immuables) ; la conformité aux règles actuelles est informative et datée."""
    o, pids, ben = t["o"], t["pids"], t["emps"]["ben"]
    run(o, pids[OCT])
    v1 = o.get(f"/periods/{pids[OCT]}/versions").json()[-1]
    assert v1["has_context"] and v1["engine_version"]
    assert v1["conformity"]["creation"]["status"] == "conforme" and v1["conformity"]["current"]["status"] == "conforme"
    assert v1["conformity"]["current"]["checked_at"]
    # changement fait ensuite : Ben n'est plus autorisé sur Alpha
    assert o.put(f"/employees/{ben['id']}", json={"code": "ben", "name": "Ben", "brands": {}}).status_code == 200
    before_params = o.get(f"/periods/{pids[OCT]}/params").json()
    row = next(x for x in o.get(f"/periods/{pids[OCT]}/versions").json() if x["id"] == v1["id"])
    assert row["conformity"]["creation"]["status"] == "conforme"  # ses propres règles : toujours conforme
    assert row["conformity"]["current"]["status"] == "non_conforme" and row["conformity"]["current"]["violations"] > 0
    assert (row["state"], row["assignments"]) == (v1["state"], v1["assignments"])  # rien n'est modifié par la vérification
    assert o.get(f"/periods/{pids[OCT]}/params").json()["frozen_at"] == before_params["frozen_at"]
    det = o.get(f"/versions/{v1['id']}/conformity").json()
    assert any(i["code"] == "BRAND_NOT_ELIGIBLE" and i["employee"] == "Ben" for i in det["current"]["items"])
    assert det["params"]["mode"] in ("frozen", "current") and det["run"] and det["run"]["id"]
    # une nouvelle version n'écrase jamais le contexte des précédentes
    assert o.post(f"/periods/{pids[OCT]}/versions", json={"label": "Copie"}).status_code == 201
    import app.models as m
    from app.db import tenant_session
    from sqlalchemy import select
    with tenant_session(t["o"].get("/auth/me").json()["tenant_id"]) as db:
        rows = list(db.scalars(select(m.ScheduleVersion).where(m.ScheduleVersion.period_id == __import__("uuid").UUID(pids[OCT])).order_by(m.ScheduleVersion.number)))
        first = next(r for r in rows if str(r.id) == v1["id"])
        assert first.context and first.context_hash and len({r.context_hash for r in rows}) >= 2  # contexte propre à chaque version
        first_hash = first.context_hash
    with pytest.raises(Exception):  # immuable, garanti par la base
        with tenant_session(t["o"].get("/auth/me").json()["tenant_id"]) as db:
            r = db.get(m.ScheduleVersion, __import__("uuid").UUID(v1["id"]))
            r.context = {**r.context, "params": {"mode": "falsifié"}}
            db.flush()
    with tenant_session(t["o"].get("/auth/me").json()["tenant_id"]) as db:
        assert db.get(m.ScheduleVersion, __import__("uuid").UUID(v1["id"])).context_hash == first_hash


def test_version_sans_contexte_marquee_contexte_incomplet():
    from types import SimpleNamespace
    from app.versioning import version_conformity
    v = SimpleNamespace(snapshot=[{"slot_key": "X|2026-10-01"}], context=None, engine_version=None)
    out = version_conformity(v)
    assert out["creation"]["status"] == "contexte_incomplet" and out["creation"]["violations"] is None and out["current"] is None


def test_exports_dans_l_identite_rose_et_blanc(t):
    import io
    from openpyxl import load_workbook
    o, pids = t["o"], t["pids"]
    run(o, pids[OCT])
    wb = load_workbook(io.BytesIO(o.get(f"/periods/{pids[OCT]}/export.xlsx").content))
    ws = wb["Planning"]
    head = ws["A1"]
    assert head.fill.fgColor.rgb.endswith("CC0256") and head.font.bold and head.font.color.rgb.endswith("FFFFFF")
    assert ws.freeze_panes == "A2" and ws["A2"].fill.fgColor.rgb.endswith("FDF6F9") and ws.auto_filter.ref  # lignes alternées blanc rosé
    pdf = o.get(f"/periods/{pids[OCT]}/export.pdf").content
    assert pdf.startswith(b"%PDF") and len(pdf) > 2000


def test_absence_sur_un_planning_valide_propose_une_revision(t):
    o, pids = t["o"], t["pids"]
    run(o, pids[OCT])
    v = o.post(f"/periods/{pids[OCT]}/versions", json={"label": "Officielle"}).json()
    assert o.post(f"/versions/{v['id']}/validate").status_code == 200
    a = o.get(f"/periods/{pids[OCT]}/schedule").json()["assignments"][0]
    before = sched(o, pids[OCT])
    r = o.put(f"/employees/{a['employee_id']}/unavailable-dates", json={"dates": [a["day"]]})
    assert r.status_code == 200 and r.json()["revisions"] and r.json()["revisions"][0]["period_id"] == pids[OCT]
    assert any(s["assignment_id"] == a["assignment_id"] for s in r.json()["revisions"][0]["shifts"])
    notes = [n for n in o.get("/notifications").json()["items"] if n["kind"] == "revision_needed"]
    assert len(notes) == 1 and "Révision proposée" in notes[0]["title"]
    assert sched(o, pids[OCT]) == before  # rien n'est modifié automatiquement
    comp = o.get(f"/periods/{pids[OCT]}/compatibility").json()
    assert comp["official"] and any(i["code"] == "UNAVAILABLE" for i in comp["items"])
    o.put(f"/employees/{a['employee_id']}/unavailable-dates", json={"dates": []})
    o.put(f"/employees/{a['employee_id']}/unavailable-dates", json={"dates": [a["day"]]})  # même absence redéclarée : pas de doublon non lu
    again = o.get("/notifications").json()["items"]
    assert len([n for n in again if n["kind"] == "revision_needed"]) == 1


def test_planning_mensuel_individuel_lecture_seule_et_compteurs_exacts(t):
    o, pids, ana = t["o"], t["pids"], t["emps"]["ana"]
    run(o, pids[OCT])
    rows = [a for a in o.get(f"/periods/{pids[OCT]}/schedule").json()["assignments"] if a["employee_id"] == ana["id"]]
    free = next(f"2026-10-{d:02d}" for d in range(1, 32) if f"2026-10-{d:02d}" not in {a["day"] for a in rows})
    o.put(f"/employees/{ana['id']}/unavailable-dates", json={"dates": [free]})
    periods_before = len(o.get("/periods").json())
    r = o.get(f"/employees/{ana['id']}/month?month=2026-10").json()
    assert r["label"] == "Octobre 2026" and r["has_plan"] and r["period"]["id"] == pids[OCT] and len(r["days"]) == 31
    assert r["totals"]["effective_minutes"] == sum(a["effective_minutes"] for a in rows)
    assert r["totals"]["days_worked"] == len({a["day"] for a in rows})
    import datetime as dt
    assert r["totals"]["sundays_worked"] == len({a["day"] for a in rows if dt.date.fromisoformat(a["day"]).weekday() == 6})
    assert r["limits"]["monthly_cap_minutes"] == 10560
    day = next(x for x in r["days"] if x["date"] == free)
    assert day["off"]["kind"] == "indisponible" and not day["assignments"]
    worked = next(x for x in r["days"] if x["assignments"])
    s0 = worked["assignments"][0]
    assert {"start", "end", "break_minutes", "site_name", "brands", "effective_minutes"} <= set(s0)
    for mo in ("2026-12", "2027-01", "2027-03"):  # passage d'année et mois sans planning : rien n'est créé
        x = o.get(f"/employees/{ana['id']}/month?month={mo}").json()
        assert x["month"] == mo and (mo != "2027-03" or (x["period"] is None and not x["has_plan"]))
    assert len(o.get("/periods").json()) == periods_before
    o.put(f"/employees/{ana['id']}/unavailable-dates", json={"dates": []})
