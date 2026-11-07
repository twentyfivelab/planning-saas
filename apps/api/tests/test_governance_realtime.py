"""Dérogations réservées aux rôles d'encadrement (jamais auto-approuvées), temps réel entre managers, report sécurisé des quotas historiques."""
import json
import threading
import time
import uuid

import pytest
from redis import Redis
from sqlalchemy import select

from app import models as m
from app.config import settings
from app.db import tenant_session
from app.realtime import channel
from app.seed import seed
from tests.conftest import make_client


@pytest.fixture(scope="module")
def t():
    domain = f"{uuid.uuid4().hex[:8]}.example"
    out = seed(domain=domain)

    def login(email, pw=out["password"]):
        c = make_client()
        r = c.post("/auth/login", json={"email": email, "password": pw})
        assert r.status_code == 200, r.text
        c.headers["X-CSRF-Token"] = r.json()["csrf_token"]
        return c
    o = login(f"owner@{domain}")
    emps = {e["code"]: e for e in o.get("/employees").json()}
    pid = o.get("/periods").json()[0]["id"]
    r = o.post(f"/periods/{pid}/runs", json={"time_limit_s": 20}, headers={"Idempotency-Key": f"k-{uuid.uuid4()}"})
    assert r.status_code == 202
    return dict(o=o, login=login, domain=domain, tenant=out["tenant_id"], planner=login(f"planner@{domain}"),
                collab=login(f"collaborateur@{domain}"), emps=emps, pid=pid)


def sched(t):
    return t["o"].get(f"/periods/{t['pid']}/schedule").json()["assignments"]


def unavailable_case(t):
    """Un shift non verrouillé et un collaborateur autorisé, libre autour de ce jour, rendu indisponible : alerte DÉROGEABLE garantie."""
    rows = sched(t)
    for a in rows:
        if a["locked"] or a["day"][8:] in ("01", "08", "15", "22", "29"):
            continue
        near = {x["employee_id"] for x in rows if abs(int(x["day"][8:]) - int(a["day"][8:])) <= 1}
        for code, e in t["emps"].items():
            if e["id"] not in near and code != "sabrina" and all(b in e["brands"] for b in a["allocations"]):
                assert t["o"].put(f"/employees/{e['id']}/unavailable-dates", json={"dates": [a["day"]]}).status_code == 200
                return a, code
    raise AssertionError("aucun cas")


def assign(c, t, code, a, **kw):
    return c.post(f"/periods/{t['pid']}/manual-assign", json={"employee_id": t["emps"][code]["id"], "shift_id": a["shift_id"], **kw})


# ---------- 1. qui peut approuver une dérogation ----------
def test_collaborator_and_planner_can_never_approve_a_derogation(t):
    a, code = unavailable_case(t)
    before = {x["assignment_id"]: x["employee"] for x in sched(t)}
    assert assign(t["collab"], t, code, a, force=True).status_code == 403  # un collaborateur ne modifie rien
    d = assign(t["planner"], t, code, a).json()["detail"]
    assert d["code"] == "needs_confirmation" and d["can_override"] is False and "manager" in d["refusal"]
    f = assign(t["planner"], t, code, a, force=True)
    assert f.status_code == 403 and f.json()["detail"]["code"] == "forbidden"
    assert {x["assignment_id"]: x["employee"] for x in sched(t)} == before
    t["o"].put(f"/employees/{t['emps'][code]['id']}/unavailable-dates", json={"dates": []})


def test_soft_preference_alert_also_needs_an_authorised_role(t):
    rows = sched(t)
    a = next(x for x in rows if not x["locked"] and x["site"] in ("GVA3", "GVA9") and x["day"][8:] not in ("01", "08", "15", "22", "29"))
    near = {x["employee_id"] for x in rows if abs(int(x["day"][8:]) - int(a["day"][8:])) <= 1}
    code, e = next((c, e) for c, e in t["emps"].items() if e["id"] not in near and c != "sabrina" and all(b in e["brands"] for b in a["allocations"]))
    body = {k: e[k] for k in ("code", "name", "brands", "allocation_weight", "active", "max_days_count", "max_days_period", "sunday_quota", "sunday_mode")}
    pref = "soir" if a["start"] < "09:00:00" else "matin"
    t["o"].put(f"/employees/{e['id']}", json={**body, "time_pref": pref, "time_pref_strict": False})
    try:
        r = assign(t["planner"], t, code, a)
        assert r.status_code == 409 and {i["code"]: i["level"] for i in r.json()["detail"]["issues"]}.get("TIME_PREF") == "soft"
        assert assign(t["planner"], t, code, a, force=True).status_code == 403
    finally:
        t["o"].put(f"/employees/{e['id']}", json={**body, "time_pref": None, "time_pref_strict": False})


def test_a_manager_cannot_approve_a_derogation_that_concerns_themselves(t):
    a, code = unavailable_case(t)
    o = t["o"]
    email = f"chef-{uuid.uuid4().hex[:6]}@{t['domain']}"
    pw = "Manager-Pass-For-Tests-42"
    r = o.post("/users", json={"email": email, "name": "Chef concerné", "role": "manager", "password": pw, "employee_id": t["emps"][code]["id"]})
    assert r.status_code == 201, r.text
    chef = t["login"](email, pw)
    d = assign(chef, t, code, a).json()["detail"]
    assert d["can_override"] is False and "vous concerne" in d["refusal"]
    assert assign(chef, t, code, a, force=True).status_code == 403  # pas d'auto-approbation
    ok = assign(o, t, code, a, force=True, reason="validé par la direction")  # un autre responsable le peut
    assert ok.status_code == 200
    h = o.get(f"/periods/{t['pid']}/history").json()[0]
    assert h["forced"] and h["by"] == "Owner"
    # retrait d'un shift verrouillé qui le concerne : refusé pour lui, possible pour un autre responsable
    mine = next(x for x in sched(t) if x["shift_id"] == a["shift_id"])
    assert chef.delete(f"/assignments/{mine['assignment_id']}?force=true").status_code == 403
    assert o.delete(f"/assignments/{mine['assignment_id']}?force=true").status_code == 204
    o.put(f"/employees/{t['emps'][code]['id']}/unavailable-dates", json={"dates": []})


def test_non_derogable_rules_stay_blocked_even_for_the_owner(t):
    rows = sched(t)
    a = next(x for x in rows if not x["locked"])
    other = next(x for x in rows if x["day"] == a["day"] and x["employee_id"] != a["employee_id"])
    code = next(c for c, e in t["emps"].items() if e["id"] == other["employee_id"])
    r = assign(t["o"], t, code, a, force=True)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "blocked"


# ---------- 2. temps réel ----------
def test_every_committed_change_is_published_instantly_and_rollbacks_are_not(t):
    r = Redis.from_url(settings.redis_url)
    ps = r.pubsub()
    ps.subscribe(channel(t["tenant"]))
    ps.get_message(timeout=1)  # confirmation d'abonnement
    e = t["emps"]["jane"]
    t0 = time.time()
    assert t["o"].put(f"/employees/{e['id']}/unavailable-dates", json={"dates": ["2026-11-20"]}).status_code == 200
    msg = None
    while time.time() - t0 < 3 and msg is None:
        msg = ps.get_message(ignore_subscribe_messages=True, timeout=0.5)
    assert msg is not None and "availability.dates" in json.loads(msg["data"])["actions"]
    assert time.time() - t0 < 2  # annoncé en moins de 2 s, pas au rythme d'une interrogation
    # une requête refusée (rien de validé) n'annonce rien
    assert t["collab"].put(f"/employees/{e['id']}/unavailable-dates", json={"dates": []}).status_code == 403
    assert ps.get_message(ignore_subscribe_messages=True, timeout=1) is None
    t["o"].put(f"/employees/{e['id']}/unavailable-dates", json={"dates": []})
    ps.close()


def test_event_stream_requires_a_session_and_permission(t):
    anon = make_client()
    assert anon.get("/events").status_code == 401


def test_event_stream_delivers_a_change_from_another_manager(t):
    got: list = []
    done = threading.Event()

    def listen():
        with t["planner"].stream("GET", "/events") as resp:
            assert resp.status_code == 200 and resp.headers["content-type"].startswith("text/event-stream")
            for line in resp.iter_lines():
                got.append(line)
                if line.startswith("event: ready"):
                    done.set()
                if line.startswith("event: change"):
                    return
    th = threading.Thread(target=listen, daemon=True)
    th.start()
    assert done.wait(5)
    t0 = time.time()
    t["o"].put(f"/employees/{t['emps']['jane']['id']}/unavailable-dates", json={"dates": ["2026-11-21"]})
    th.join(5)
    assert any(x.startswith("event: change") for x in got) and time.time() - t0 < 5
    t["o"].put(f"/employees/{t['emps']['jane']['id']}/unavailable-dates", json={"dates": []})


# ---------- 3. report sécurisé des quotas historiques ----------
def test_legacy_sunday_quota_report_never_changes_history_or_validated_plans(t):
    o = t["o"]
    e = t["emps"]["chloe"] if "chloe" in t["emps"] else next(iter(t["emps"].values()))
    body = {k: e[k] for k in ("code", "name", "brands", "allocation_weight", "active", "max_days_count", "max_days_period", "time_pref", "time_pref_strict")}
    assert o.put(f"/employees/{e['id']}", json={**body, "sunday_quota": 2, "sunday_mode": "max"}).status_code == 200  # ancienne valeur unique
    dec = o.post("/periods/ensure", json={"year": 2026, "month": 12}).json()["id"]
    # novembre « validé » : une version publiée (simulée en base, la démo étant exploratoire)
    vid = o.post(f"/periods/{t['pid']}/versions").json()["id"]
    with tenant_session(t["tenant"]) as db:
        db.get(m.ScheduleVersion, uuid.UUID(vid)).published = True
    snap_v = o.get(f"/periods/{t['pid']}/versions").json()
    snap_a = sorted((x["slot_key"], x["employee"]) for x in sched(t))
    q = lambda pid: o.get(f"/periods/{pid}/sunday-summary").json()["employees"][e["code"]]  # noqa: E731
    before = (q(t["pid"])["quota"], q(t["pid"])["mode"], q(dec)["quota"], q(dec)["mode"])
    assert before == (2, "max", 2, "max")
    # première saisie mensuelle (mars 2027) : report sécurisé
    r = o.put(f"/employees/{e['id']}/month-params/2027-03", json={"sunday_quota": 1, "sunday_mode": "exact"})
    assert r.status_code == 200
    assert (q(t["pid"])["quota"], q(t["pid"])["mode"], q(dec)["quota"], q(dec)["mode"]) == before  # valeurs effectives inchangées
    assert sorted((x["slot_key"], x["employee"]) for x in sched(t)) == snap_a  # aucune affectation modifiée
    assert o.get(f"/periods/{t['pid']}/versions").json() == snap_v  # version publiée intacte
    with tenant_session(t["tenant"]) as db:
        row = db.get(m.Employee, uuid.UUID(e["id"]))
        assert row.sunday_quota == 2 and row.sunday_quota_migrated_at is not None  # valeur historique CONSERVÉE
        logs = [x.detail for x in db.scalars(select(m.AuditLog).where(m.AuditLog.action == "employee.sunday_quota_migration", m.AuditLog.entity_id == e["id"]))]
    assert len(logs) == 1 and "2026-11-01" in logs[0]["months_copied"] and "2026-11-01" in logs[0]["published_months"]
    # idempotent : une nouvelle saisie ne relance jamais le report
    o.put(f"/employees/{e['id']}/month-params/2027-03", json={"sunday_quota": 0, "sunday_mode": "max"})
    with tenant_session(t["tenant"]) as db:
        assert db.query(m.AuditLog).filter(m.AuditLog.action == "employee.sunday_quota_migration", m.AuditLog.entity_id == e["id"]).count() == 1
    mp = lambda mo: next(x for x in o.get(f"/month-params?month={mo}").json() if x["employee_id"] == e["id"])  # noqa: E731
    assert mp("2027-05")["source"] == "none"  # un mois futur ne reçoit plus la valeur historique
    # modifier un mois publié : la version publiée ne change pas, l'utilisateur est prévenu
    n = o.put(f"/employees/{e['id']}/month-params/2026-11", json={"sunday_quota": 1, "sunday_mode": "max"}).json()
    assert n["published"] is True and n["notice"]
    assert o.get(f"/periods/{t['pid']}/versions").json() == snap_v and sorted((x["slot_key"], x["employee"]) for x in sched(t)) == snap_a
