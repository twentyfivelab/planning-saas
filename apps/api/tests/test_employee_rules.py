"""Fiche collaborateur (jours max, préférence horaire, quota de dimanches) : persistance, validation, moteur, compteur."""
import uuid
from datetime import date, time

import pytest
from sqlalchemy import select

from app import models as m
from app.db import tenant_session
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
    p = login(f"planner@{domain}")
    emps = {e["code"]: e for e in p.get("/employees").json()}
    pid = p.get("/periods").json()[0]["id"]
    return dict(planner=p, auditor=login(f"auditor@{domain}"), owner=login(f"owner@{domain}"), emps=emps, pid=pid, tenant=out["tenant_id"])


def body(e, **kw):
    base = {k: e[k] for k in ("code", "name", "brands", "allocation_weight", "active", "max_days_count", "max_days_period",
                              "time_pref", "time_pref_strict", "sunday_quota", "sunday_mode")}
    return {**base, **kw}


def put(t, code, **kw):
    e = t["emps"][code]
    return t["planner"].put(f"/employees/{e['id']}", json=body(e, **kw))


def reset(t, code):
    r = put(t, code, max_days_count=None, max_days_period=None, time_pref=None, time_pref_strict=False, sunday_quota=None, sunday_mode="max")
    assert r.status_code == 200, r.text


def counter(t):
    return t["planner"].get(f"/periods/{t['pid']}/sunday-summary").json()


def test_fields_persist_and_pas_de_preference_means_null(t):
    r = put(t, "zaki", max_days_count=4, max_days_period="week", time_pref="soir", time_pref_strict=True, sunday_quota=2, sunday_mode="exact")
    assert r.status_code == 200
    got = {e["code"]: e for e in t["planner"].get("/employees").json()}["zaki"]
    assert (got["max_days_count"], got["max_days_period"], got["time_pref"], got["time_pref_strict"], got["sunday_quota"], got["sunday_mode"]) == (4, "week", "soir", True, 2, "exact")
    reset(t, "zaki")
    got = {e["code"]: e for e in t["planner"].get("/employees").json()}["zaki"]
    assert got["max_days_count"] is None and got["max_days_period"] is None and got["time_pref"] is None and got["sunday_quota"] is None and got["sunday_mode"] == "max"


@pytest.mark.parametrize("kw", [
    dict(max_days_count=4, max_days_period=None), dict(max_days_count=None, max_days_period="week"),
    dict(max_days_count=8, max_days_period="week"), dict(max_days_count=32, max_days_period="month"), dict(max_days_count=0, max_days_period="month"),
    dict(time_pref="aprem"), dict(time_pref=None, time_pref_strict=True), dict(sunday_quota=6), dict(sunday_quota=-1), dict(sunday_mode="exactement"),
])
def test_invalid_parameters_are_rejected(t, kw):
    assert put(t, "mila", **kw).status_code == 422


def test_weekly_7_and_monthly_31_are_accepted_and_auditor_cannot_edit(t):
    assert put(t, "mila", max_days_count=7, max_days_period="week").status_code == 200
    assert put(t, "mila", max_days_count=31, max_days_period="month").status_code == 200
    reset(t, "mila")
    e = t["emps"]["mila"]
    assert t["auditor"].put(f"/employees/{e['id']}", json=body(e, sunday_quota=1)).status_code == 403


def test_sunday_counter_updates_immediately_without_running_the_solver(t):
    c0 = counter(t)
    assert c0["total"] == 35 and c0["per_sunday"] == 7 and len(c0["sundays"]) == 5 and c0["reserved"] == 0 and c0["remaining_to_reserve"] == 35
    assert c0["by_site"] == {"GVA3": 15, "Pilar": 10, "GVA9": 10}
    put(t, "mila", sunday_quota=2, sunday_mode="exact")
    assert (counter(t)["reserved"], counter(t)["remaining_to_reserve"]) == (2, 33)
    put(t, "abdu", sunday_quota=3, sunday_mode="exact")
    c = counter(t)
    assert (c["reserved"], c["remaining_to_reserve"]) == (5, 30)
    put(t, "sabrina", sunday_quota=4, sunday_mode="max")  # « maximum » : attribué aussi, détaillé à part
    c = counter(t)
    assert (c["reserved"], c["reserved_exact"], c["reserved_max"], c["remaining_to_reserve"]) == (9, 5, 4, 26)
    for code in ("mila", "abdu", "sabrina"):
        reset(t, code)
    assert counter(t)["remaining_to_reserve"] == 35


def test_engine_receives_and_respects_the_fiche_parameters(t):
    put(t, "zaki", max_days_count=4, max_days_period="week", sunday_quota=0)
    put(t, "sahra", max_days_count=20, max_days_period="month")
    put(t, "mila", sunday_quota=2, sunday_mode="exact")
    put(t, "abdu", sunday_quota=3, sunday_mode="exact")
    put(t, "kristina", time_pref="soir", time_pref_strict=True)
    p = t["planner"]
    r = p.post(f"/periods/{t['pid']}/runs", json={"time_limit_s": 30}, headers={"Idempotency-Key": f"k-{uuid.uuid4()}"})
    assert r.status_code == 202, r.text
    sched = p.get(f"/periods/{t['pid']}/schedule").json()
    by = {}
    for a in sched["assignments"]:
        by.setdefault(a["employee"], []).append(a)
    assert not [a for a in by.get("Zaki", []) if a["day"][5:7] and date.fromisoformat(a["day"]).weekday() == 6]
    zaki_weeks = {}
    for a in by.get("Zaki", []):
        zaki_weeks.setdefault(date.fromisoformat(a["day"]).isocalendar()[:2], set()).add(a["day"])
    assert all(len(v) <= 4 for v in zaki_weeks.values())
    assert len(by["Sahra"]) <= 20
    sundays = lambda n: len([a for a in by.get(n, []) if date.fromisoformat(a["day"]).weekday() == 6])  # noqa: E731
    assert sundays("Mila") <= 2 and sundays("Abdu") <= 3
    kr = by.get("Kristina", [])
    assert kr and all(a["start"][:2] in ("12",) or a["start"].startswith("12:") for a in kr if a["site"] in ("GVA3", "GVA9", "Pilar"))  # soir : 12 h et plus
    assert p.get(f"/periods/{t['pid']}/conflicts").json()["hard_violations"] == []
    c = counter(t)
    assert c["total"] == 35 and c["planned"] + c["unplanned"] == 35
    assert c["planned"] == sum(1 for a in sched["assignments"] if date.fromisoformat(a["day"]).weekday() == 6)
    for code in ("zaki", "sahra", "mila", "abdu", "kristina"):
        reset(t, code)


def test_manual_change_violating_a_strict_rule_is_flagged_immediately(t):
    p = t["planner"]
    sched = p.get(f"/periods/{t['pid']}/schedule").json()
    sun = next(a for a in sched["assignments"] if date.fromisoformat(a["day"]).weekday() == 6 and a["site"] == "GVA3")
    put(t, "yasmine", sunday_quota=0)  # 0 dimanche : contrainte dure
    moved = p.put(f"/assignments/{sun['assignment_id']}", json={"employee_id": t["emps"]["yasmine"]["id"]})
    assert moved.status_code == 200 and any(v.startswith("SUNDAY_QUOTA: Yasmine") for v in moved.json()["conflicts"])
    back = p.put(f"/assignments/{sun['assignment_id']}", json={"employee_id": sun["employee_id"]})
    assert back.json()["conflicts"] == []
    reset(t, "yasmine")


def test_weekly_limit_counts_days_planned_in_the_neighbouring_period(t):
    """Semaine du 26 oct. au 1er nov. : 4 jours déjà planifiés en octobre -> Zaki (plafond 4/semaine) n'a pas le dimanche 1er nov."""
    p = t["planner"]
    oct_p = p.post("/periods", json={"name": "Octobre 2026", "start_date": "2026-10-01", "end_date": "2026-10-31"}).json()
    zaki = t["emps"]["zaki"]["id"]
    with tenant_session(t["tenant"]) as db:
        for i, d in enumerate((26, 27, 28, 29)):
            sh = m.Shift(tenant_id=uuid.UUID(t["tenant"]), period_id=uuid.UUID(oct_p["id"]), slot_key=f"OCT|{d}", day=date(2026, 10, d), site_code="GVA3",
                         start_time=time(10), end_time=time(19), break_minutes=60, presence_minutes=540, effective_minutes=480)
            db.add(sh)
            db.flush()
            db.add(m.Assignment(tenant_id=uuid.UUID(t["tenant"]), period_id=uuid.UUID(oct_p["id"]), shift_id=sh.id,
                                employee_id=uuid.UUID(zaki), source="manual"))
    put(t, "zaki", max_days_count=4, max_days_period="week")
    r = p.post(f"/periods/{t['pid']}/runs", json={"time_limit_s": 30}, headers={"Idempotency-Key": f"k-{uuid.uuid4()}"})
    assert r.status_code == 202
    sched = p.get(f"/periods/{t['pid']}/schedule").json()
    assert not [a for a in sched["assignments"] if a["employee"] == "Zaki" and a["day"] == "2026-11-01"]
    report = p.get(f"/runs/{r.json()['run_id']}/diagnostic").json()["report"]
    assert not any(i["code"] == "WEEK_BOUNDARY_HISTORY_MISSING" for i in report["missing_data"])  # historique fourni
    assert p.get(f"/periods/{t['pid']}/conflicts").json()["hard_violations"] == []
    reset(t, "zaki")
    with tenant_session(t["tenant"]) as db:
        for a in db.scalars(select(m.Assignment).where(m.Assignment.period_id == uuid.UUID(oct_p["id"]))):
            db.delete(a)


def test_a_plan_violating_a_hard_rule_is_never_saved(t, monkeypatch):
    """Garde-fou : si la vérification indépendante détecte une violation, rien n'est enregistré et la cause est tracée."""
    import app.optimize as opt
    p = t["planner"]
    before = p.get(f"/periods/{t['pid']}/schedule").json()["assignments"]
    real = opt.solve

    def rigged(inp, cancel=None):
        res = real(inp, cancel)
        res.hard_violations = ["OVERLAP: test simulé"]
        return res
    monkeypatch.setattr(opt, "solve", rigged)
    r = p.post(f"/periods/{t['pid']}/runs", json={"time_limit_s": 10}, headers={"Idempotency-Key": f"k-{uuid.uuid4()}"})
    assert r.status_code == 202
    assert p.get(f"/runs/{r.json()['run_id']}").json()["status"] == "erreur"
    after = p.get(f"/periods/{t['pid']}/schedule").json()["assignments"]
    assert {a["assignment_id"] for a in after} == {a["assignment_id"] for a in before}  # planning inchangé
    assert any(c for c in t["auditor"].get("/audit").json() if c["action"] == "optimization.requested")
