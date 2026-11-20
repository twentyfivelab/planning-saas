"""Gestion manuelle des shifts depuis le calendrier : liste du jour, attribution, transfert, contraintes avec dérogation, historique."""
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
    owner = login(f"owner@{domain}")
    emps = {e["code"]: e for e in owner.get("/employees").json()}
    pid = owner.get("/periods").json()[0]["id"]
    r = owner.post(f"/periods/{pid}/runs", json={"time_limit_s": 30}, headers={"Idempotency-Key": f"k-{uuid.uuid4()}"})
    assert r.status_code == 202
    return dict(o=owner, planner=login(f"planner@{domain}"), auditor=login(f"auditor@{domain}"), emps=emps, pid=pid)


def sched(t):
    return t["o"].get(f"/periods/{t['pid']}/schedule").json()["assignments"]


def day_shifts(t, day, emp=None):
    q = f"?day={day}" + (f"&employee_id={t['emps'][emp]['id']}" if emp else "")
    return t["o"].get(f"/periods/{t['pid']}/day-shifts{q}").json()


def assign(t, code, shift_id, client="o", **kw):
    return t[client].post(f"/periods/{t['pid']}/manual-assign", json={"employee_id": t["emps"][code]["id"], "shift_id": shift_id, **kw})


def set_dates(t, code, dates):
    return t["o"].put(f"/employees/{t['emps'][code]['id']}/unavailable-dates", json={"dates": dates})


def find_case(t, sites=None):
    """Un shift non verrouillé occupé par A, et un collaborateur B autorisé sur sa marque, libre ce jour-là."""
    rows = sched(t)
    for a in rows:
        if a["locked"] or (sites and a["site"] not in sites) or a["day"][8:] in ("01", "07", "08", "14", "15", "21", "22", "28", "29"):
            continue
        near = {x["employee_id"] for x in rows if abs(int(x["day"][8:]) - int(a["day"][8:])) <= 1}  # ni repos ni série en jeu
        busy = near
        for code, e in t["emps"].items():
            if e["id"] in busy or not e["active"] or code in ("sabrina",):
                continue
            if all(b in e["brands"] for b in a["allocations"]) and e["sunday_quota"] is None and not e.get("time_pref"):
                return a, code
    raise AssertionError("aucun cas de test")


def test_day_shifts_lists_every_shift_with_status_and_assignee(t):
    a, code = find_case(t)
    d = day_shifts(t, a["day"], code)
    row = next(r for r in d["shifts"] if r["assignment_id"] == a["assignment_id"])
    assert row["status"] == "assigned" and row["assigned_to"]["name"] == a["employee"] and row["brands"] and row["site"] == a["site"]
    assert d["employee"]["name"] == t["emps"][code]["name"] and d["can_override"] is True
    assert len(d["shifts"]) == len([x for x in sched(t) if x["day"] == a["day"]]) + len(
        [u for u in t["o"].get(f"/periods/{t['pid']}/schedule").json()["uncovered"] if u["day"] == a["day"]])


def test_day_shifts_flags_a_shift_whose_need_is_gone_without_blocking_the_day(t):
    """Un shift resté dans le planning alors que son besoin n'existe plus (marque archivée depuis, besoin supprimé) : signalé sur CE
    shift (non attribuable), la liste du jour reste disponible et les autres shifts attribuables (auparavant : 422 pour toute la journée)."""
    from datetime import date as _date, time as _time
    from app import models as m
    from app.db import tenant_session
    a, code = find_case(t)
    tid = t["o"].get("/auth/me").json()["tenant_id"]
    with tenant_session(tid) as db:
        sh = m.Shift(tenant_id=uuid.UUID(tid), period_id=uuid.UUID(t["pid"]), slot_key=f"BESOIN-DISPARU|{a['day']}", day=_date.fromisoformat(a["day"]),
                     site_code=a["site"], start_time=_time(10), end_time=_time(17), break_minutes=60, presence_minutes=420, effective_minutes=360)
        db.add(sh)
        db.flush()
        gone = str(sh.id)
    try:
        r = t["o"].get(f"/periods/{t['pid']}/day-shifts", params={"day": a["day"], "employee_id": t["emps"][code]["id"]})
        assert r.status_code == 200, r.text
        rows = {x["shift_id"]: x for x in r.json()["shifts"]}
        assert [i["code"] for i in rows[gone]["issues"]] == ["UNKNOWN_NEED"] and rows[gone]["issues"][0]["level"] == "blocking"
        assert all(i["code"] != "UNKNOWN_NEED" for sid, x in rows.items() if sid != gone for i in x["issues"])  # les autres : contrôles habituels
        assert assign(t, code, gone).status_code == 422  # toujours refusé à l'attribution
    finally:
        with tenant_session(tid) as db:
            db.execute(m.Shift.__table__.delete().where(m.Shift.__table__.c.id == uuid.UUID(gone)))


def test_transfer_moves_the_same_shift_without_double_counting(t):
    a, code = find_case(t)
    before = sched(t)
    r = assign(t, code, a["shift_id"])
    assert r.status_code == 200, r.text
    assert r.json()["kind"] == "transfer" and r.json()["forced"] is False
    after = sched(t)
    assert len(after) == len(before)  # aucun shift créé ni dupliqué
    moved = next(x for x in after if x["assignment_id"] == a["assignment_id"])
    assert moved["employee"] == t["emps"][code]["name"] and moved["locked"] and moved["source"] == "manual"
    assert (moved["start"], moved["end"], moved["site"], moved["allocations"]) == (a["start"], a["end"], a["site"], a["allocations"])
    mins = lambda rows, name: sum(x["effective_minutes"] for x in rows if x["employee"] == name)  # noqa: E731
    assert mins(after, a["employee"]) == mins(before, a["employee"]) - a["effective_minutes"]
    assert mins(after, moved["employee"]) == mins(before, moved["employee"]) + a["effective_minutes"]
    h = t["o"].get(f"/periods/{t['pid']}/history").json()[0]
    assert (h["kind"], h["from"], h["to"], h["by"]) == ("Transfert", a["employee"], moved["employee"], "Owner") and h["day"] == a["day"]


def test_free_shift_can_be_assigned_after_removal_and_second_shift_same_day_is_blocked(t):
    rows = sched(t)
    a = next(x for x in rows if not x["locked"] and x["day"] > "2026-11-09")
    assert t["o"].delete(f"/assignments/{a['assignment_id']}").status_code == 204
    free = next(r for r in day_shifts(t, a["day"])["shifts"] if r["shift_id"] == a["shift_id"])
    assert free["status"] == "available" and free["assigned_to"] is None
    near = {x["employee_id"] for x in sched(t) if abs(int(x["day"][8:]) - int(a["day"][8:])) <= 1}  # ni repos ni série en jeu
    code = next(c for c, e in t["emps"].items() if e["id"] not in near and all(b in e["brands"] for b in a["allocations"]) and c != "sabrina" and not e.get("time_pref"))
    used: dict = {}
    for x in sched(t):
        used[x["employee_id"]] = used.get(x["employee_id"], 0) + x["effective_minutes"]
    other = next(x for x in sched(t) if x["day"] == a["day"] and used[x["employee_id"]] + a["effective_minutes"] <= 10560)  # sous le plafond
    twice = assign(t, next(c for c, e in t["emps"].items() if e["id"] == other["employee_id"]), a["shift_id"])
    # deuxième shift le même jour : confirmation explicite exigée (enregistrement provisoire + rappel « À régulariser »), rien sans elle
    assert twice.status_code == 409 and twice.json()["detail"]["code"] == "needs_confirmation"
    same = next(i for i in twice.json()["detail"]["issues"] if i["code"] == "SAME_DAY")
    assert same["level"] == "override" and "À régulariser" in same["message"]
    n = len(sched(t))
    r = assign(t, code, a["shift_id"])
    assert r.status_code == 200 and r.json()["kind"] == "assign"
    assert len(sched(t)) == n + 1
    assert next(x for x in sched(t) if x["shift_id"] == a["shift_id"])["employee"] == t["emps"][code]["name"]
    assert t["o"].get(f"/periods/{t['pid']}/history").json()[0]["kind"] == "Attribution"


def test_constraint_alert_then_override_by_admin_only_and_planning_untouched_on_cancel(t):
    a, code = find_case(t)
    assert set_dates(t, code, [a["day"]]).status_code == 200
    snapshot = {x["assignment_id"]: x["employee"] for x in sched(t)}
    r = assign(t, code, a["shift_id"])  # sans dérogation : rien n'est modifié
    d = r.json()["detail"]
    assert r.status_code == 409 and d["code"] == "needs_confirmation" and d["can_override"] is True
    assert any(i["code"] == "UNAVAILABLE" and "indisponible" in i["message"] for i in d["issues"])
    assert {x["assignment_id"]: x["employee"] for x in sched(t)} == snapshot  # « Annuler » = planning inchangé
    assert assign(t, code, a["shift_id"], client="planner", force=True).status_code in (403, 409)  # le planificateur ne déroge pas
    assert {x["assignment_id"]: x["employee"] for x in sched(t)} == snapshot
    ok = assign(t, code, a["shift_id"], force=True, reason="Remplacement de dernière minute")
    assert ok.status_code == 200 and ok.json()["forced"] is True
    h = t["o"].get(f"/periods/{t['pid']}/history").json()[0]
    assert h["forced"] and h["reason"] == "Remplacement de dernière minute" and h["issues"]
    assert any("UNAVAILABLE" in c for c in ok.json()["conflicts"])  # le conflit est enregistré et signalé
    set_dates(t, code, [])


def test_brand_not_authorised_is_an_overridable_alert(t):
    rows = sched(t)
    a = next(x for x in rows if not x["locked"] and x["day"] > "2026-11-09" and "Cartier" in x["allocations"])
    busy = {x["employee_id"] for x in rows if x["day"] == a["day"]}
    code = next(c for c, e in t["emps"].items() if e["id"] not in busy and "Cartier" not in e["brands"] and c != "sabrina")
    r = assign(t, code, a["shift_id"])
    assert r.status_code == 409 and any(i["code"] == "BRAND_NOT_AUTHORIZED" for i in r.json()["detail"]["issues"])
    assert next(x for x in sched(t) if x["assignment_id"] == a["assignment_id"])["employee"] == a["employee"]


def test_locked_shift_asks_for_authorisation_and_soft_preference_never_blocks(t):
    a, code = find_case(t, sites=("GVA3", "GVA9"))
    t["o"].post(f"/assignments/{a['assignment_id']}/lock")
    r = assign(t, code, a["shift_id"])
    assert r.status_code == 409 and any(i["code"] == "LOCKED" for i in r.json()["detail"]["issues"])
    e = t["emps"][code]
    body = {k: e[k] for k in ("code", "name", "brands", "allocation_weight", "active", "max_days_count", "max_days_period", "sunday_quota", "sunday_mode")}
    pref = "soir" if a["start"] < "09:00:00" else "matin"
    assert t["o"].put(f"/employees/{e['id']}", json={**body, "time_pref": pref, "time_pref_strict": False}).status_code == 200
    r = assign(t, code, a["shift_id"])
    kinds = {i["code"]: i["level"] for i in r.json()["detail"]["issues"]}
    assert kinds.get("TIME_PREF") == "soft"  # la préférence souple est signalée mais n'est jamais bloquante
    r = assign(t, code, a["shift_id"], force=True)  # verrou : autorisation d'administration ; la préférence souple n'empêche rien
    assert r.status_code == 200
    assert t["o"].put(f"/employees/{e['id']}", json={**body, "time_pref": None, "time_pref_strict": False}).status_code == 200


def test_non_derogable_rule_stays_blocked(t, monkeypatch):
    import app.routers.manual_shifts as ms
    a, code = find_case(t)
    set_dates(t, code, [a["day"]])
    monkeypatch.setattr(ms, "_non_derogable", lambda ctx: {"UNAVAILABLE"})
    r = assign(t, code, a["shift_id"], force=True)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "blocked" and r.json()["detail"]["can_override"] is False
    set_dates(t, code, [])


def test_remove_locked_needs_force_and_is_recorded(t):
    a = next(x for x in sched(t) if x["locked"])
    assert t["o"].delete(f"/assignments/{a['assignment_id']}").status_code == 409
    assert t["planner"].delete(f"/assignments/{a['assignment_id']}?force=true").status_code == 403
    assert t["o"].delete(f"/assignments/{a['assignment_id']}?force=true&reason=absence").status_code == 204
    h = t["o"].get(f"/periods/{t['pid']}/history?employee_id={a['employee_id']}").json()[0]
    assert h["kind"] == "Retrait" and h["from"] == a["employee"] and h["to"] is None and h["reason"] == "absence"


def test_read_only_role_cannot_modify_and_history_filters_by_employee(t):
    a, code = find_case(t)
    assert assign(t, code, a["shift_id"], client="auditor").status_code == 403
    assert t["auditor"].get(f"/periods/{t['pid']}/history").status_code == 200
    eid = t["emps"][code]["id"]
    name = t["emps"][code]["name"]
    hist = t["o"].get(f"/periods/{t['pid']}/history?employee_id={eid}").json()
    assert all(name in (h["from"], h["to"]) for h in hist)



def test_double_affectation_confirmee_rappel_a_regulariser_cycle_complet(t):
    """Remplacement confirmé malgré une affectation le même jour : enregistré provisoirement, rappel persistant rattaché aux deux
    affectations, conflit bloquant la validation, puis disparition automatique dès que l'affectation initiale est retirée."""
    o, pid = t["o"], t["pid"]
    rows = sched(t)
    a = next(x for x in rows if not x["locked"] and x["day"] > "2026-11-09")
    used: dict = {}
    for x in rows:
        used[x["employee_id"]] = used.get(x["employee_id"], 0) + x["effective_minutes"]
    holder = next(x for x in rows if x["day"] == a["day"] and x["employee_id"] != a["employee_id"] and not x["locked"]
                  and used[x["employee_id"]] + a["effective_minutes"] <= 10560
                  and all(b in next(e for e in t["emps"].values() if e["id"] == x["employee_id"])["brands"] for b in a["allocations"]))
    code = next(c for c, e in t["emps"].items() if e["id"] == holder["employee_id"])
    r = assign(t, code, a["shift_id"], force=True)
    assert r.status_code == 200, r.text
    assert r.json()["regularizations"] == 1
    items = o.get(f"/periods/{pid}/regularizations").json()
    it = next(x for x in items if x["employee_id"] == holder["employee_id"])
    assert it["new"]["shift_id"] == a["shift_id"] and it["initial"]["assignment_id"] == holder["assignment_id"] and it["day"] == a["day"]
    assert assign(t, code, a["shift_id"], force=True).status_code == 409  # même shift déjà à lui : aucun rappel en double
    assert len([x for x in o.get(f"/periods/{pid}/regularizations").json() if x["employee_id"] == holder["employee_id"]]) == 1
    assert any("OVERLAP" in c or "REST" in c for c in o.get(f"/periods/{pid}/conflicts").json()["hard_violations"])  # conflit à corriger
    v = o.post(f"/periods/{pid}/versions").json()
    assert o.post(f"/versions/{v['id']}/validate").status_code == 409  # validation refusée tant que la double affectation existe
    # traitement : retrait de l'affectation initiale -> le rappel disparaît, le poste libéré reste dans les besoins non couverts
    assert o.delete(f"/assignments/{holder['assignment_id']}").status_code == 204
    assert not [x for x in o.get(f"/periods/{pid}/regularizations").json() if x["employee_id"] == holder["employee_id"]]
    assert any(u["shift_id"] == holder["shift_id"] for u in o.get(f"/periods/{pid}/schedule").json()["uncovered"])
