"""Plusieurs mois, paramètres mensuels, frontière entre deux mois, pondérations personnalisées, transfert atomique et concurrent."""
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
    return dict(o=o, planner=login(f"planner@{domain}"), auditor=login(f"auditor@{domain}"), emps=emps, nov=nov)


def run(c, pid, partial=False, **cfg):
    r = c.post(f"/periods/{pid}/{'reoptimize' if partial else 'runs'}", json={"time_limit_s": 20, **cfg}, headers={"Idempotency-Key": f"k-{uuid.uuid4()}"})
    assert r.status_code == 202, r.text
    res = c.get(f"/runs/{r.json()['run_id']}").json()
    assert res["status"] == "termine", res
    return res


def sched(c, pid):
    return c.get(f"/periods/{pid}/schedule").json()["assignments"]


def key(rows):
    return sorted((a["slot_key"], a["employee"], a["start"], a["end"], a["locked"]) for a in rows)


def ensure(c, y, mo):
    r = c.post("/periods/ensure", json={"year": y, "month": mo})
    assert r.status_code == 200, r.text
    return r.json()


# ---------- I. calendrier et besoins calculés ----------
def test_calendar_is_computed_from_configured_needs_for_any_month(t):
    o = t["o"]
    nov = o.get("/calendar?year=2026&month=11").json()
    assert (nov["days"], nov["sundays"], nov["saturdays"]) == (30, 5, 4) and nov["sunday_shifts_total"] == 35 and nov["has_period"]
    assert nov["sunday_shifts_per_site"] == {"GVA3": 15, "GVA9": 10, "Pilar": 10}  # 3 + 2 + 2 par dimanche
    dec = o.get("/calendar?year=2026&month=12").json()
    assert (dec["days"], dec["sundays"], dec["saturdays"]) == (31, 4, 4) and dec["sunday_shifts_total"] == 28
    assert dec["sunday_dates"] == ["2026-12-06", "2026-12-13", "2026-12-20", "2026-12-27"]
    assert not dec["has_period"] and dec["budgets_missing"] is True and dec["budgets"] == []  # aucun budget inventé
    jan = o.get("/calendar?year=2027&month=1").json()
    assert (jan["days"], jan["sundays"], jan["sunday_shifts_total"]) == (31, 5, 35)
    feb = o.get("/calendar?year=2027&month=2").json()
    assert (feb["days"], feb["sundays"], feb["sunday_shifts_total"]) == (28, 4, 28)
    assert o.get("/calendar?year=2028&month=2").json()["days"] == 29  # année bissextile
    assert {b["brand"] for b in dec["brands"]} >= {"Cartier", "Ploom GVA3"} and dec["shifts_total"] > 0


# ---------- II. un planning indépendant par mois ----------
def test_each_month_has_its_own_plan_and_other_months_are_never_overwritten(t):
    o = t["o"]
    run(o, t["nov"])
    nov_before = key(sched(o, t["nov"]))
    assert nov_before
    dec = ensure(o, 2026, 12)
    assert dec["created"] and dec["name"] == "Décembre 2026" and dec["start_date"] == "2026-12-01" and dec["end_date"] == "2026-12-31"
    again = ensure(o, 2026, 12)
    assert not again["created"] and again["id"] == dec["id"]  # rouvrir ne crée rien
    res = run(o, dec["id"])
    dec_plan = sched(o, dec["id"])
    assert dec_plan and all("2026-12-01" <= a["day"] <= "2026-12-31" for a in dec_plan)
    assert key(sched(o, t["nov"])) == nov_before  # novembre intact
    rep = o.get(f"/runs/{res['id']}/diagnostic").json()["report"]
    assert any(i["code"] == "BRAND_BUDGET_MISSING" for i in rep["missing_data"] + rep["diagnostics"]) or rep["missing_data"]  # données manquantes signalées
    jan = ensure(o, 2027, 1)
    run(o, jan["id"])
    assert key(sched(o, t["nov"])) == nov_before and sched(o, dec["id"])  # novembre ET décembre intacts
    periods = {p["name"] for p in o.get("/periods").json()}
    assert {"Décembre 2026", "Janvier 2027"} <= periods
    t["dec"], t["jan"] = dec["id"], jan["id"]


def test_sunday_counter_follows_the_selected_month(t):
    o = t["o"]
    assert o.get(f"/periods/{t['nov']}/sunday-summary").json()["total"] == 35
    assert o.get(f"/periods/{t['dec']}/sunday-summary").json()["total"] == 28
    assert o.get(f"/periods/{t['jan']}/sunday-summary").json()["total"] == 35


# ---------- III. paramètres mensuels indépendants ----------
def test_monthly_sunday_quotas_are_independent_between_months(t):
    o, e = t["o"], t["emps"]["zaki"]["id"]
    assert o.put(f"/employees/{e}/month-params/2026-11", json={"sunday_quota": 2, "sunday_mode": "max"}).status_code == 200
    assert o.put(f"/employees/{e}/month-params/2026-12", json={"sunday_quota": 3, "sunday_mode": "exact"}).status_code == 200
    get = lambda mo: next(x for x in o.get(f"/month-params?month={mo}").json() if x["employee_id"] == e)  # noqa: E731
    assert (get("2026-11")["sunday_quota"], get("2026-11")["sunday_mode"]) == (2, "max")
    assert (get("2026-12")["sunday_quota"], get("2026-12")["sunday_mode"]) == (3, "exact")
    assert o.put(f"/employees/{e}/month-params/2026-12", json={"sunday_quota": 1, "sunday_mode": "exact"}).status_code == 200
    assert get("2026-11")["sunday_quota"] == 2  # modifier décembre ne change jamais novembre
    assert get("2027-03")["source"] == "none"
    s_nov = o.get(f"/periods/{t['nov']}/sunday-summary").json()
    s_dec = o.get(f"/periods/{t['dec']}/sunday-summary").json()
    z = lambda s: s["employees"]["zaki"]  # noqa: E731
    assert z(s_nov)["quota"] == 2 and z(s_dec)["quota"] == 1
    assert o.put(f"/employees/{e}/month-params/2026-12", json={"sunday_quota": 5, "sunday_mode": "max"}).status_code == 422  # 4 dimanches en décembre
    assert o.put(f"/employees/{e}/month-params/2026-12", json={"sunday_quota": None, "sunday_mode": "exact"}).status_code == 422
    assert t["auditor"].put(f"/employees/{e}/month-params/2026-12", json={"sunday_quota": 1, "sunday_mode": "max"}).status_code == 403


def test_legacy_sheet_quota_is_carried_over_so_no_other_month_changes(t):
    o, e = t["o"], t["emps"]["jane"]
    body = {k: e[k] for k in ("code", "name", "brands", "allocation_weight", "active", "max_days_count", "max_days_period", "time_pref", "time_pref_strict", "sunday_mode")}
    assert o.put(f"/employees/{e['id']}", json={**body, "sunday_quota": 1}).status_code == 200  # ancienne valeur « globale »
    assert o.put(f"/employees/{e['id']}/month-params/2026-12", json={"sunday_quota": 2, "sunday_mode": "max"}).status_code == 200
    get = lambda mo: next(x for x in o.get(f"/month-params?month={mo}").json() if x["employee_id"] == e["id"])  # noqa: E731
    assert get("2026-11")["sunday_quota"] == 1 and get("2026-12")["sunday_quota"] == 2 and get("2027-01")["sunday_quota"] == 1
    assert o.get(f"/employees/{e['id']}").status_code in (200, 404, 405)


# ---------- IV. frontière entre deux mois ----------
def test_rest_and_limits_are_enforced_across_the_month_boundary(t):
    o = t["o"]
    sched_nov = sched(o, t["nov"])
    busy = {a["employee"] for a in sched_nov if a["day"] in ("2026-11-29", "2026-11-30")}
    cand = next(c for c, e in t["emps"].items() if e["name"] not in busy and "Ploom GVA9" in e["brands"] and c != "sabrina")
    tpl = next(x for x in o.get("/brand-schedules").json()["Ploom GVA9"] if x["end"].startswith("21:30"))
    r = o.post(f"/periods/{t['nov']}/assignments", json={"employee_id": t["emps"][cand]["id"], "day": "2026-11-30", "brand_code": "Ploom GVA9", "template_id": tpl["template_id"]})
    assert r.status_code == 201, r.text
    # le moteur de décembre voit la fin de service du 30/11 à 21h30 : pas de prise de poste avant 08h30 le 1er décembre
    run(o, t["dec"])
    name = t["emps"][cand]["name"]
    first = [a for a in sched(o, t["dec"]) if a["employee"] == name and a["day"] == "2026-12-01"]
    assert all(a["start"] >= "08:30:00" for a in first), first
    assert not o.get(f"/periods/{t['dec']}/conflicts").json()["hard_violations"]
    # attribution manuelle d'un shift du 1er décembre à 06h00 : alerte de repos (dérogeable), valeur atteinte indiquée
    early = next(a for a in sched(o, t["dec"]) if a["day"] == "2026-12-01" and a["start"] <= "07:00:00" and a["employee"] != name and not a["locked"])
    d = o.post(f"/periods/{t['dec']}/manual-assign", json={"employee_id": t["emps"][cand]["id"], "shift_id": early["shift_id"]})
    assert d.status_code == 409
    rest = next(i for i in d.json()["detail"]["issues"] if i["code"] == "REST")
    assert rest["level"] == "override" and rest["limit"] == "11 h" and float(rest["reached"].split()[0]) < 11 and rest["consequence"]
    assert o.get(f"/periods/{t['dec']}/schedule").json()["assignments"]  # rien n'a changé
    assert next(a for a in sched(o, t["dec"]) if a["assignment_id"] == early["assignment_id"])["employee"] == early["employee"]


# ---------- V. pondérations ----------
def test_weights_are_saved_validated_and_reach_the_solver(t):
    o = t["o"]
    w = o.get("/settings/weights").json()
    assert [c["key"] for c in w["criteria"]] == ["fairness", "time_pref", "brand_priority", "individual_priority", "hour_targets", "sunday_balance", "alternation", "family", "days_balance", "cost"]
    assert {c["key"]: c["value"] for c in w["criteria"]}["fairness"] == 80 and not w["customised"] and all(c["description"] for c in w["criteria"])
    assert o.put("/settings/weights", json={"criteria": {"nope": 5}}).status_code == 422
    assert o.put("/settings/weights", json={"criteria": {"family": 101}}).status_code == 422
    assert t["auditor"].put("/settings/weights", json={"criteria": {"family": 10}}).status_code == 403
    r = o.put("/settings/weights", json={"criteria": {"family": 0, "fairness": 100}})
    assert r.status_code == 200 and r.json()["customised"]
    assert {c["key"]: c["value"] for c in o.get("/settings/weights").json()["criteria"]}["family"] == 0  # persistant
    # janvier a déjà un planning : il garde les pondérations de sa génération, sauf choix explicite des paramètres actuels
    kept = run(o, t["jan"], partial=False)
    assert o.get(f"/runs/{kept['id']}/diagnostic").json()["report"]["weights_used"]["family"] != 0
    res = run(o, t["jan"], partial=False, params="current")
    rep = o.get(f"/runs/{res['id']}/diagnostic").json()["report"]
    assert rep["weights_used"]["family"] == 0 and rep["weights_used"]["fairness"] > 3 and "criteria_scores" in rep
    last = o.get("/settings/weights").json()["last_run"]
    assert last["weights_used"]["family"] == 0 and "by_criterion" in last
    # un poids peut aussi être fourni pour UNE génération (avancé) sans toucher aux réglages enregistrés
    res2 = run(o, t["jan"], weights={"coverage": 1234})
    assert o.get(f"/runs/{res2['id']}/diagnostic").json()["report"]["weights_used"]["coverage"] == 1234
    reset = o.post("/settings/weights/reset").json()
    assert not reset["customised"] and {c["key"]: c["value"] for c in reset["criteria"]}["family"] == 90


def test_changing_a_weight_changes_the_objective_function(t):
    o = t["o"]
    o.post("/settings/weights/reset")
    base = run(o, t["jan"], params="current")
    b = o.get(f"/runs/{base['id']}/diagnostic").json()["report"]
    o.put("/settings/weights", json={"advanced": {"stability": 0, "site_change": 0}, "criteria": {"alternation": 100}})
    again = run(o, t["jan"], params="current")  # nouvelles pondérations appliquées au planning existant : choix explicite
    a = o.get(f"/runs/{again['id']}/diagnostic").json()["report"]
    assert b["weights_used"]["alternation"] != a["weights_used"]["alternation"] and a["weights_used"]["site_change"] == 0
    assert a["objective"].get("site_change", 0) == 0
    o.post("/settings/weights/reset")


# ---------- VI. transfert atomique et concurrent ----------
def _case(t, pid):
    rows = sched(t["o"], pid)
    for a in rows:
        if a["locked"] or a["day"][8:] in ("01", "07", "08", "14", "15", "21", "22", "28", "29"):
            continue
        near = {x["employee_id"] for x in rows if abs(int(x["day"][8:]) - int(a["day"][8:])) <= 1}
        for code, e in t["emps"].items():
            if e["id"] not in near and e["active"] and code != "sabrina" and all(b in e["brands"] for b in a["allocations"]):
                return a, code
    raise AssertionError("aucun cas")


def test_transfer_is_atomic_when_something_fails_midway(t, monkeypatch):
    import app.routers.manual_shifts as ms
    o = t["o"]
    a, code = _case(t, t["jan"])
    before = key(sched(o, t["jan"]))

    def boom(*args, **kw):
        raise RuntimeError("panne simulée après la modification")
    monkeypatch.setattr(ms, "audit", boom)
    try:
        r = o.post(f"/periods/{t['jan']}/manual-assign", json={"employee_id": t["emps"][code]["id"], "shift_id": a["shift_id"], "force": True})
        assert r.status_code == 500
    except RuntimeError:
        pass
    monkeypatch.undo()
    after = sched(o, t["jan"])
    assert key(after) == before  # rien n'est enregistré : jamais de transfert partiel
    assert sum(1 for x in after if x["shift_id"] == a["shift_id"]) == 1


def test_concurrent_modification_is_detected_and_never_double_assigns(t):
    o = t["o"]
    a, code = _case(t, t["jan"])
    other = next(c for c, e in t["emps"].items() if c not in (code, "sabrina") and e["name"] != a["employee"] and all(b in e["brands"] for b in a["allocations"])
                 and e["id"] not in {x["employee_id"] for x in sched(o, t["jan"]) if x["day"] == a["day"]})
    seen = a["employee_id"]  # deux managers voient le même titulaire
    ok = o.post(f"/periods/{t['jan']}/manual-assign", json={"employee_id": t["emps"][code]["id"], "shift_id": a["shift_id"], "expected_from": seen, "force": True})
    assert ok.status_code == 200
    stale = t["planner"].post(f"/periods/{t['jan']}/manual-assign", json={"employee_id": t["emps"][other]["id"], "shift_id": a["shift_id"], "expected_from": seen, "force": True})
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "stale"
    holders = [x for x in sched(o, t["jan"]) if x["shift_id"] == a["shift_id"]]
    assert len(holders) == 1 and holders[0]["employee"] == t["emps"][code]["name"]
    rev1 = o.get("/revision").json()["revision"]
    o.delete(f"/assignments/{holders[0]['assignment_id']}?force=true")
    assert o.get("/revision").json()["revision"] != rev1  # les autres clients se resynchronisent


def test_alert_details_name_rule_limit_reached_and_consequence(t):
    import datetime as dt
    o = t["o"]
    rows = sched(o, t["jan"])
    wk = lambda d: dt.date.fromisoformat(d).isocalendar()[:2]  # noqa: E731
    found = None
    for mine in rows:
        e = next(x for x in t["emps"].values() if x["name"] == mine["employee"])
        for s2 in rows:
            if (s2["employee"] != mine["employee"] and not s2["locked"] and wk(s2["day"]) == wk(mine["day"]) and abs((dt.date.fromisoformat(s2["day"]) - dt.date.fromisoformat(mine["day"])).days) >= 2
                    and all(b in e["brands"] for b in s2["allocations"]) and not any(x["employee"] == e["name"] and x["day"] == s2["day"] for x in rows)):
                found = (e, s2)
                break
        if found:
            break
    e, s2 = found
    # exception propre à janvier (le planning de janvier garde les paramètres habituels de sa création ; une exception du mois s'y applique)
    assert o.put(f"/employees/{e['id']}/month-params/2027-01", json={"max_days_set": True, "max_days_count": 1, "max_days_period": "week"}).status_code == 200
    try:
        r = o.post(f"/periods/{t['jan']}/manual-assign", json={"employee_id": e["id"], "shift_id": s2["shift_id"]})
        issue = next(i for i in r.json()["detail"]["issues"] if i["code"] == "MAX_DAYS_WEEK")
        assert r.status_code == 409 and issue["level"] == "override" and issue["limit"].startswith("1 ") and int(issue["reached"].split()[0]) >= 2
        assert e["name"] in issue["message"] and issue["consequence"] and issue["rule"]
        assert next(x for x in sched(o, t["jan"]) if x["shift_id"] == s2["shift_id"])["employee"] == s2["employee"]  # « Annuler » : rien ne bouge
    finally:
        o.put(f"/employees/{e['id']}/month-params/2027-01", json={"max_days_set": False})
