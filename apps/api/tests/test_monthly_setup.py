"""Préparation des plannings mensuels : effectif, exceptions du mois, budgets et marques par mois, sites et animations versionnés,
statuts / archivage / brouillon, vérification avant génération, cohérence du moteur avec la configuration du mois."""
import datetime as dt
import uuid

import pytest

from app.seed import seed
from tests.conftest import make_client


@pytest.fixture(scope="module")
def t():
    domain = f"{uuid.uuid4().hex[:8]}.example"
    out = seed(domain=domain)

    def login(email):
        c = make_client()
        r = c.post("/auth/login", json={"email": email, "password": out["password"]})
        assert r.status_code == 200, r.text
        c.headers["X-CSRF-Token"] = r.json()["csrf_token"]
        return c
    o = login(f"owner@{domain}")
    emps = {e["code"]: e for e in o.get("/employees").json()}
    nov = o.get("/periods").json()[0]["id"]
    return dict(o=o, auditor=login(f"auditor@{domain}"), emps=emps, nov=nov)


def run(o, pid, partial=False):
    r = o.post(f"/periods/{pid}/{'reoptimize' if partial else 'runs'}", json={"time_limit_s": 20}, headers={"Idempotency-Key": f"k-{uuid.uuid4()}"})
    assert r.status_code == 202, r.text
    res = o.get(f"/runs/{r.json()['run_id']}").json()
    assert res["status"] == "termine", res
    return res


def sched(o, pid):
    return o.get(f"/periods/{pid}/schedule").json()["assignments"]


def period(o, pid):
    return next(p for p in o.get("/periods").json() if p["id"] == pid)


def test_1_new_month_is_a_draft_until_generated(t):
    o = t["o"]
    run(o, t["nov"])
    assert period(o, t["nov"])["status"] == "generated"
    dec = o.post("/periods/ensure", json={"year": 2026, "month": 12}).json()
    assert dec["created"] and dec["start_date"] == "2026-12-01" and dec["end_date"] == "2026-12-31"
    p = period(o, dec["id"])
    assert (p["status"], p["status_label"], p["assignments"]) == ("draft", "Brouillon", 0)  # choisir la période ne génère rien
    assert o.patch(f"/periods/{dec['id']}/wizard", json={"step": 3}).json()["wizard_step"] == 3  # brouillon repris plus tard
    assert period(o, dec["id"])["wizard_step"] == 3
    t["dec"] = dec["id"]


def test_2_roster_defaults_to_all_active_and_exclusion_is_month_only(t):
    o, dec = t["o"], t["dec"]
    r = o.get(f"/periods/{dec}/roster").json()
    actives = [e for e in t["emps"].values() if e["active"]]
    assert r["included"] == len(actives) and all(x["included"] for x in r["employees"] if x["state"] != "inactive")
    zaki = t["emps"]["zaki"]["id"]
    nov_zaki = [a for a in sched(o, t["nov"]) if a["employee"] == "Zaki"]
    r = o.put(f"/periods/{dec}/roster", json={"employees": [{"employee_id": zaki, "included": False, "reason": "absent en décembre"}]}).json()
    assert r["included"] == len(actives) - 1 and next(x for x in r["employees"] if x["code"] == "zaki")["state"] == "excluded"
    assert next(x for x in o.get(f"/periods/{t['nov']}/roster").json()["employees"] if x["code"] == "zaki")["included"]  # novembre : toujours retenu
    assert next(e for e in o.get("/employees").json() if e["code"] == "zaki")["active"] is True  # fiche intacte, pas désactivé
    run(o, dec)
    assert not [a for a in sched(o, dec) if a["employee"] == "Zaki"]  # aucun shift en décembre
    assert [a for a in sched(o, t["nov"]) if a["employee"] == "Zaki"] == nov_zaki  # novembre intact
    a = next(x for x in sched(o, dec) if not x["locked"])
    d = o.post(f"/periods/{dec}/manual-assign", json={"employee_id": zaki, "shift_id": a["shift_id"], "force": True})
    assert d.status_code == 409 and any(i["code"] == "EXCLUDED_FROM_PERIOD" and i["level"] == "blocking" for i in d.json()["detail"]["issues"])
    assert o.get(f"/periods/{dec}/readiness").json()["employees"]["excluded"] == ["Zaki"]


def test_2b_ended_contract_is_distinct_from_a_temporary_exclusion(t):
    o = t["o"]
    e = t["emps"]["yasmine"] if "yasmine" in t["emps"] else t["emps"]["pierre"]
    assert o.post("/contracts", json={"employee_id": e["id"], "start_date": "2026-01-01", "end_date": "2026-11-15"}).status_code == 201
    x = next(x for x in o.get(f"/periods/{t['dec']}/roster").json()["employees"] if x["employee_id"] == e["id"])
    assert (x["state"], x["selectable"], x["contract_end"]) == ("contract_ended", False, "2026-11-15")
    assert o.put(f"/periods/{t['dec']}/roster", json={"employees": [{"employee_id": e["id"], "included": True}]}).status_code == 422
    assert next(x for x in o.get(f"/periods/{t['nov']}/roster").json()["employees"] if x["employee_id"] == e["id"])["state"] == "included"


def test_3_month_exception_on_max_days_leaves_other_months_unchanged(t):
    o, mila = t["o"], t["emps"]["mila"]
    r = o.put(f"/employees/{mila['id']}/month-params/2026-12", json={"max_days_set": True, "max_days_count": 3, "max_days_period": "week"})
    assert r.status_code == 200 and (r.json()["max_days_count"], r.json()["max_days_period"], r.json()["max_days_set"]) == (3, "week", True)
    mp = lambda mo: next(x for x in o.get(f"/month-params?month={mo}").json() if x["employee_id"] == mila["id"])  # noqa: E731
    assert mp("2026-11")["max_days_set"] is False and mp("2026-11")["max_days_count"] == mila["max_days_count"]
    assert mp("2026-12")["sunday_quota"] is None  # les dimanches du mois ne sont pas touchés par l'exception
    dates = ["2026-12-17", "2026-12-18"]
    assert o.put(f"/employees/{mila['id']}/unavailable-dates", json={"dates": dates}).status_code == 200
    run(o, t["dec"])
    rows = [a for a in sched(o, t["dec"]) if a["employee"] == "Mila"]
    weeks: dict = {}
    for a in rows:
        weeks.setdefault(dt.date.fromisoformat(a["day"]).isocalendar()[:2], set()).add(a["day"])
    assert rows and max(len(v) for v in weeks.values()) <= 3 and not any(a["day"] in dates for a in rows)
    nov_weeks: dict = {}
    for a in [a for a in sched(o, t["nov"]) if a["employee"] == "Mila"]:
        nov_weeks.setdefault(dt.date.fromisoformat(a["day"]).isocalendar()[:2], set()).add(a["day"])
    assert max(len(v) for v in nov_weeks.values()) > 3  # novembre n'a pas reçu l'exception
    assert o.put(f"/employees/{mila['id']}/month-params/2026-12", json={"max_days_set": True, "max_days_count": 9, "max_days_period": "week"}).status_code == 422


def test_4_budget_of_a_month_never_changes_another_month(t):
    o = t["o"]
    nov_v = next(b for b in o.get(f"/periods/{t['nov']}/brands").json() if b["code"] == "Valmont")
    assert nov_v["budget_minutes"] == 136 * 60
    r = o.put(f"/periods/{t['dec']}/brands/Valmont", json={"budget_minutes": 80 * 60})
    assert r.status_code == 200 and r.json()["budget_minutes"] == 80 * 60 and r.json()["reference_minutes"] == 136 * 60
    assert next(b for b in o.get(f"/periods/{t['nov']}/brands").json() if b["code"] == "Valmont")["budget_minutes"] == 136 * 60
    dv = next(b for b in o.get(f"/periods/{t['dec']}/brands").json() if b["code"] == "Valmont")
    assert dv["need_mandatory_minutes"] + dv["need_optional_minutes"] > 0 and dv["schedules"] and dv["sites"]
    need = dv["need_mandatory_minutes"] + dv["need_optional_minutes"]
    if dv["need_mandatory_minutes"]:  # écart besoins / budget signalé (jamais corrigé en silence)
        low = o.put(f"/periods/{t['dec']}/brands/Valmont", json={"budget_minutes": dv["need_mandatory_minutes"] - 60}).json()
        assert any("dépassent le budget" in c["text"] for c in low["checks"])
    high = o.put(f"/periods/{t['dec']}/brands/Valmont", json={"budget_minutes": need + 100 * 60}).json()
    assert any("dépasse les heures possibles" in c["text"] for c in high["checks"]) and high["budget_minutes"] == need + 100 * 60
    assert o.put(f"/periods/{t['dec']}/brands/Valmont", json={"budget_minutes": 80 * 60}).json()["budget_minutes"] == 80 * 60
    lindt = next(b for b in o.get(f"/periods/{t['nov']}/brands").json() if b["code"] == "Lindt")
    assert any("sans aucun besoin" in c["text"] for c in lindt["checks"])
    nobud = next(b for b in o.get(f"/periods/{t['dec']}/brands").json() if b["code"] == "Cartier")
    assert nobud["budget_minutes"] is None and any("Aucun budget" in c["text"] for c in nobud["checks"])  # jamais imposé depuis novembre
    assert t["auditor"].put(f"/periods/{t['dec']}/brands/Valmont", json={"budget_minutes": 1}).status_code == 403


def test_5_new_confectionery_site_gva7_is_used_by_the_engine_from_its_first_month(t):
    """GVA7 : site de confiserie (Lindt, Favarger, Toblerone…), créé et configuré depuis l'interface."""
    o = t["o"]
    assert o.post("/catalog/sites", json={"name": "GVA7"}).json()["code"] == "GVA7"
    assert o.post("/catalog/sites", json={"name": "GVA7"}).status_code == 409
    assert o.post("/catalog/brands", json={"name": "Favarger"}).status_code == 201
    a = o.post("/catalog/animations", json={"site_code": "GVA7", "brand_code": "Favarger", "start": "09:00", "end": "18:00", "weekdays": [0, 1, 2, 3, 4],
                                             "headcount": 2, "from_month": "2026-12"})
    assert a.status_code == 201, a.text
    ids = [t["emps"][c]["id"] for c in ("aziza", "valerie", "sahra")]
    assert set(o.post("/catalog/brands/Favarger/authorize", json={"employee_ids": ids, "level": "priority"}).json()["authorized"]) == {"Aziza", "Valérie", "Sahra"}
    o.put(f"/periods/{t['dec']}/brands/Favarger", json={"budget_minutes": 2 * 23 * 8 * 60})
    site = next(s for s in o.get(f"/periods/{t['dec']}/sites").json() if s["code"] == "GVA7")
    assert site["active"] and site["shifts"] == 2 * 23 and site["brands"][0]["code"] == "Favarger"  # 23 jours ouvrés × 2 personnes
    assert not any(s["code"] == "GVA7" and s["shifts"] for s in o.get(f"/periods/{t['nov']}/sites").json())  # novembre non concerné
    cat = o.get("/catalog?month=2026-12").json()
    an = next(s for s in cat["sites"] if s["code"] == "GVA7")["animations"][0]
    assert (an["start"], an["end"], an["headcount"], an["weekdays"]) == ("09:00", "18:00", 2, [0, 1, 2, 3, 4])
    assert "09:00–18:00" in next(b for b in o.get(f"/periods/{t['dec']}/brands").json() if b["code"] == "Favarger")["schedules"]
    run(o, t["dec"])
    g7 = [x for x in sched(o, t["dec"]) if x["site"] == "GVA7"]
    assert g7 and {x["employee"] for x in g7} <= {"Aziza", "Valérie", "Sahra"}
    assert len({x["slot_key"] for x in g7}) == len(g7)  # deux personnes = deux shifts distincts, jamais une double affectation
    assert not o.get(f"/periods/{t['dec']}/conflicts").json()["hard_violations"]


def test_6_history_lists_every_month_with_a_real_status_and_archive_is_read_only(t):
    o = t["o"]
    jan = o.post("/periods/ensure", json={"year": 2027, "month": 1}).json()["id"]
    run(o, jan)
    rows = {p["name"]: p for p in o.get("/periods").json()}
    assert {"Novembre 2026", "Décembre 2026", "Janvier 2027"} <= set(rows) or {"Décembre 2026", "Janvier 2027"} <= set(rows)
    assert rows["Janvier 2027"]["status"] == "generated"
    assert o.post(f"/periods/{jan}/archive").json()["status"] == "archived"
    a = next(x for x in sched(o, jan) if not x["locked"])
    assert o.post(f"/periods/{jan}/manual-assign", json={"employee_id": t["emps"]["sahra"]["id"], "shift_id": a["shift_id"]}).status_code == 409
    assert o.post(f"/periods/{jan}/runs", json={"time_limit_s": 5}).status_code == 409
    assert sched(o, jan)  # toujours consultable
    assert o.post(f"/periods/{jan}/unarchive").json()["status"] == "generated"
    t["jan"] = jan
    draft = o.post("/periods/ensure", json={"year": 2027, "month": 3}).json()["id"]
    assert o.delete(f"/periods/{draft}").status_code == 204  # un brouillon s'abandonne
    assert o.delete(f"/periods/{jan}").status_code == 409  # un planning généré ne se supprime jamais


def test_7_editing_a_generated_month_keeps_everything_else(t):
    o, dec = t["o"], t["dec"]
    before = {x["assignment_id"]: x["employee"] for x in sched(o, dec)}
    rows = sched(o, dec)
    ok = {x["employee_id"] for x in o.get(f"/periods/{dec}/roster").json()["employees"] if x["included"]}
    # un shift et un remplaçant autorisé, libre la veille, le jour même et le lendemain : indépendant de la solution trouvée par le moteur
    a, to = next((x, e) for x in rows if not x["locked"] and "2026-12-08" <= x["day"] <= "2026-12-30" for e in t["emps"].values()
                 if e["id"] in ok and e["code"] != "sabrina" and e["name"] != x["employee"] and all(b in e["brands"] for b in x["allocations"])
                 and not any(y["employee"] == e["name"] and abs(int(y["day"][8:]) - int(x["day"][8:])) <= 1 for y in rows))
    holder = next(e for e in t["emps"].values() if e["name"] == a["employee"])
    o.put(f"/employees/{holder['id']}/unavailable-dates", json={"dates": [a["day"]]})
    comp = o.get(f"/periods/{dec}/compatibility").json()
    assert a["assignment_id"] in comp["flagged_assignment_ids"]
    assert {x["assignment_id"]: x["employee"] for x in sched(o, dec)} == before  # rien de régénéré automatiquement
    r = o.post(f"/periods/{dec}/manual-assign", json={"employee_id": to["id"], "shift_id": a["shift_id"], "force": True})
    assert r.status_code == 200
    after = {x["assignment_id"]: x["employee"] for x in sched(o, dec)}
    assert after[a["assignment_id"]] == to["name"] and sum(1 for k in before if before[k] != after.get(k)) == 1
    o.put(f"/employees/{holder['id']}/unavailable-dates", json={"dates": []})


def test_9_renaming_or_archiving_a_site_never_rewrites_history(t):
    o = t["o"]
    assert o.patch("/catalog/sites/GVA7", json={"name": "GVA7 Place Centrale"}).json()["code"] == "GVA7"
    g7 = [x for x in sched(o, t["dec"]) if x["site"] == "GVA7"]
    assert g7 and all(x["site_name"] == "GVA7 Place Centrale" for x in g7)  # même code : affectations conservées
    nov_gva9 = sorted(x["slot_key"] for x in sched(o, t["nov"]) if x["site"] == "GVA9")
    dec_shifts = next(s for s in o.get(f"/periods/{t['dec']}/sites").json() if s["code"] == "GVA9")["shifts"]
    assert o.patch("/catalog/sites/GVA9", json={"archived_from": "2027-01"}).status_code == 200
    assert next(s for s in o.get(f"/periods/{t['jan']}/sites").json() if s["code"] == "GVA9")["archived"] is True
    assert o.get("/calendar?year=2027&month=1").json()["sunday_shifts_total"] == 25  # GVA3 3 + Pilar 2 par dimanche × 5
    assert next(s for s in o.get(f"/periods/{t['dec']}/sites").json() if s["code"] == "GVA9")["shifts"] == dec_shifts  # décembre inchangé
    run(o, t["nov"], partial=True)
    assert sorted(x["slot_key"] for x in sched(o, t["nov"]) if x["site"] == "GVA9") == nov_gva9  # novembre : ses shifts GVA9 existent toujours
    o.patch("/catalog/sites/GVA9", json={"archived_from": ""})


def test_9b_editing_an_animation_from_a_month_versions_it(t):
    o = t["o"]
    cat = o.get("/catalog?month=2027-01").json()
    an = next(a for s in cat["sites"] if s["code"] == "GVA3" for a in s["animations"] if a["start"] == "06:00")
    dec_total = o.get("/calendar?year=2026&month=12").json()["shifts_total"]
    jan_total = o.get("/calendar?year=2027&month=1").json()["shifts_total"]
    r = o.patch(f"/catalog/animations/{an['id']}", json={"from_month": "2027-01", "headcount": 2})
    assert r.status_code == 200 and r.json()["valid_from"] == "2027-01-01"
    assert o.get("/calendar?year=2026&month=12").json()["shifts_total"] == dec_total  # décembre garde l'ancienne version
    assert o.get("/calendar?year=2027&month=1").json()["shifts_total"] > jan_total
    old = next(a for s in o.get("/catalog?month=2026-12").json()["sites"] if s["code"] == "GVA3" for a in s["animations"] if a["code"] == an["code"])
    assert old["headcount"] == 1 and old["valid_to"] == "2026-12-31"


def test_10_engine_uses_only_the_month_configuration(t):
    o, dec = t["o"], t["dec"]
    assert o.put(f"/periods/{dec}/brands/Cartier", json={"active": False}).json()["active"] is False
    rd = o.get(f"/periods/{dec}/readiness").json()
    assert "Cartier" in rd["brands"]["inactive"] and rd["employees"]["excluded"] == ["Zaki"] and rd["shifts"] > 0 and rd["sundays"] == 4
    assert any("désactivé" in i["text"] for i in rd["issues"])  # des affectations Cartier existent déjà : signalé avant de régénérer
    run(o, dec)
    rows = sched(o, dec)
    assert not any("Cartier" in x["allocations"] for x in rows) and not any(x["employee"] == "Zaki" for x in rows)
    assert any("Cartier" in x["allocations"] for x in sched(o, t["nov"]))  # novembre : Cartier toujours planifié
    assert o.put(f"/periods/{dec}/sites/Pilar", json={"active": False}).json()["active"] is False
    run(o, dec)
    assert not any(x["site"] == "Pilar" for x in sched(o, dec)) and o.get(f"/periods/{dec}/sunday-summary").json()["total"] == 4 * 5
    o.put(f"/periods/{dec}/sites/Pilar", json={"active": True})
    o.put(f"/periods/{dec}/brands/Cartier", json={"active": True})


def test_permanent_change_impact_is_reported_without_touching_plans(t):
    o = t["o"]
    rows = sched(o, t["nov"])
    a = next(x for x in rows if "Cartier" in x["allocations"])
    e = next(v for v in t["emps"].values() if v["name"] == a["employee"])
    body = {k: e[k] for k in ("code", "name", "allocation_weight", "active", "max_days_count", "max_days_period", "time_pref", "time_pref_strict", "sunday_quota", "sunday_mode")}
    brands = {k: v for k, v in e["brands"].items() if k != "Cartier"}
    o.put(f"/employees/{e['id']}", json={**body, "brands": brands})
    imp = o.get(f"/employees/{e['id']}/impact").json()
    assert any(p["name"] == "Novembre 2026" and p["hard"] > 0 for p in imp["periods"])
    assert {x["assignment_id"] for x in sched(o, t["nov"])} == {x["assignment_id"] for x in rows}  # rien modifié en silence
    o.put(f"/employees/{e['id']}", json={**body, "brands": e["brands"]})
