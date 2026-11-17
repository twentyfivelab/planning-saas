"""Calendrier d'indisponibilités, marques par collaborateur, horaires par marque, ajout manuel, compatibilité et réoptimisation."""
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
    p = login(f"planner@{domain}")
    emps = {e["code"]: e for e in p.get("/employees").json()}
    pid = p.get("/periods").json()[0]["id"]
    r = p.post(f"/periods/{pid}/runs", json={"time_limit_s": 30}, headers={"Idempotency-Key": f"k-{uuid.uuid4()}"})
    assert r.status_code == 202
    return dict(p=p, auditor=login(f"auditor@{domain}"), emps=emps, pid=pid)


def sched(t):
    return t["p"].get(f"/periods/{t['pid']}/schedule").json()["assignments"]


def run(t, partial=False, params=None):
    """`params="current"` : choix explicite d'appliquer les fiches modifiées au planning existant (sinon il garde ses paramètres)."""
    path = "reoptimize" if partial else "runs"
    body = {"time_limit_s": 30, **({"params": params} if params else {})}
    r = t["p"].post(f"/periods/{t['pid']}/{path}", json=body, headers={"Idempotency-Key": f"k-{uuid.uuid4()}"})
    assert r.status_code == 202, r.text
    return t["p"].get(f"/runs/{r.json()['run_id']}").json()


def set_brands(t, code, brands):
    e = t["emps"][code]
    body = {k: e[k] for k in ("code", "name", "allocation_weight", "active", "max_days_count", "max_days_period", "time_pref", "time_pref_strict", "sunday_quota", "sunday_mode")}
    r = t["p"].put(f"/employees/{e['id']}", json={**body, "brands": brands})
    return r


def set_dates(t, code, dates):
    return t["p"].put(f"/employees/{t['emps'][code]['id']}/unavailable-dates", json={"dates": dates})


# ---------- 1. calendrier d'indisponibilités ----------
def test_unavailable_dates_are_saved_replaced_and_recurring_days_kept(t):
    jane = t["emps"]["jane"]["id"]
    before = t["p"].get(f"/employees/{jane}/availability").json()
    assert before["weekdays"] == [1] and before["dates"] == []  # mardi récurrent fourni, conservé
    r = set_dates(t, "jane", ["2026-11-12", "2026-11-05", "2026-11-18", "2026-11-05"])
    assert r.status_code == 200 and r.json()["dates"] == ["2026-11-05", "2026-11-12", "2026-11-18"]
    got = t["p"].get(f"/employees/{jane}/availability").json()
    assert got["dates"] == ["2026-11-05", "2026-11-12", "2026-11-18"] and got["weekdays"] == [1]
    assert set_dates(t, "jane", ["2026-11-12"]).json()["dates"] == ["2026-11-12"]  # retirer = remplacer
    assert t["p"].get(f"/employees/{jane}/availability").json()["dates"] == ["2026-11-12"]
    assert set_dates(t, "jane", []).json()["dates"] == []
    assert t["p"].get(f"/employees/{jane}/availability").json()["weekdays"] == [1]


def test_unavailable_dates_validation_and_permissions(t):
    assert set_dates(t, "jane", ["pas-une-date"]).status_code == 422
    assert t["p"].put(f"/employees/{t['emps']['jane']['id']}/unavailable-dates", json={"dates": [], "x": 1}).status_code == 422
    r = t["auditor"].put(f"/employees/{t['emps']['jane']['id']}/unavailable-dates", json={"dates": ["2026-11-05"]})
    assert r.status_code == 403
    assert t["auditor"].get(f"/employees/{t['emps']['jane']['id']}/availability").status_code == 200


def test_engine_never_assigns_a_blocked_date(t):
    blocked = ["2026-11-05", "2026-11-12", "2026-11-18"]
    assert set_dates(t, "zaki", blocked).status_code == 200
    assert run(t)["status"] == "termine"
    assert not [a for a in sched(t) if a["employee"] == "Zaki" and a["day"] in blocked]
    assert t["p"].get(f"/periods/{t['pid']}/conflicts").json()["hard_violations"] == []
    set_dates(t, "zaki", [])


# ---------- 3. incompatibilités et réoptimisation ----------
def test_parameter_change_is_flagged_on_existing_plan_then_reoptimized_without_touching_locked(t):
    p = t["p"]
    assert run(t)["status"] == "termine"
    comp0 = p.get(f"/periods/{t['pid']}/compatibility").json()
    assert comp0["has_plan"] and comp0["hard"] == []
    # on bloque un jour où Sabrina travaille : le planning existant devient incompatible
    day = next(a["day"] for a in sched(t) if a["employee"] == "Sabrina")
    assert set_dates(t, "sabrina", [day]).status_code == 200
    comp = p.get(f"/periods/{t['pid']}/compatibility").json()
    assert not comp["compatible"] and any("UNAVAILABLE: Sabrina" in h for h in comp["hard"]) and comp["flagged_assignment_ids"]
    flagged = comp["flagged_assignment_ids"][0]
    # le planning n'a PAS été modifié en silence
    assert any(a["assignment_id"] == flagged for a in sched(t))
    # réoptimisation : l'affectation incompatible non verrouillée est corrigée, le reste est stable
    before = {a["slot_key"]: a["employee"] for a in sched(t)}
    assert run(t, partial=True)["status"] == "termine"
    after = {a["slot_key"]: a["employee"] for a in sched(t)}
    assert not [a for a in sched(t) if a["employee"] == "Sabrina" and a["day"] == day]
    assert p.get(f"/periods/{t['pid']}/compatibility").json()["hard"] == []
    assert sum(1 for k in after if before.get(k) != after[k]) < 40  # stabilité
    set_dates(t, "sabrina", [])


def test_locked_assignment_violating_a_new_rule_is_never_silently_moved(t):
    p = t["p"]
    a = next(x for x in sched(t) if x["employee"] == "Michael")
    p.post(f"/assignments/{a['assignment_id']}/lock")
    assert set_dates(t, "michael", [a["day"]]).status_code == 200
    snapshot = {x["assignment_id"]: x["employee"] for x in sched(t)}
    res = run(t, partial=True)
    assert res["result_status"] == "infaisable"  # le verrou est incompatible : expliqué, pas contourné
    diag = p.get(f"/runs/{res['id']}/diagnostic").json()["report"]
    assert diag["diagnostics"]
    assert {x["assignment_id"]: x["employee"] for x in sched(t)} == snapshot  # rien n'a bougé
    p.post(f"/assignments/{a['assignment_id']}/unlock")
    set_dates(t, "michael", [])


def test_time_preference_change_is_flagged_and_reoptimization_follows_it(t):
    p = t["p"]
    e = t["emps"]["abdu"]
    body = {k: e[k] for k in ("code", "name", "brands", "allocation_weight", "active", "max_days_count", "max_days_period", "sunday_quota", "sunday_mode")}
    assert run(t)["status"] == "termine"
    assert p.put(f"/employees/{e['id']}", json={**body, "time_pref": "soir", "time_pref_strict": False}).status_code == 200
    assert not [s for s in p.get(f"/periods/{t['pid']}/compatibility").json()["soft"] if s["employee"] == "Abdu"]  # le planning garde ses paramètres
    soft = p.get(f"/periods/{t['pid']}/compatibility?params=current").json()["soft"]  # ce que donneraient les paramètres actuels
    n0 = len([s for s in soft if s["employee"] == "Abdu"])
    assert n0 > 0
    # réoptimisation complète AVEC les paramètres actuels (choix explicite) : les affectations verrouillées sont conservées,
    # les autres suivent les nouveaux paramètres (une réoptimisation « partielle » privilégie la stabilité et ne déplace pas tout)
    assert run(t, params="current")["status"] == "termine"
    n1 = len([s for s in p.get(f"/periods/{t['pid']}/compatibility").json()["soft"] if s["employee"] == "Abdu"])
    assert n1 <= n0
    mine = [a for a in sched(t) if a["employee"] == "Abdu" and a["site"] in ("GVA3", "GVA9", "Pilar")]
    assert mine and sum(1 for a in mine if a["start"] >= "12:00:00") >= len(mine) * 0.8  # « soir » privilégié
    assert p.put(f"/employees/{e['id']}", json={**body, "time_pref": None, "time_pref_strict": False}).status_code == 200


# ---------- 4. marques par collaborateur ----------
def test_brand_selection_levels_validation_and_never_assigned_when_unselected(t):
    assert set_brands(t, "zaki", {"Cartier": "priority", "Valmont": "secondary", "Ploom GVA3": "reinforce"}).status_code == 200
    assert set_brands(t, "zaki", {"Cartier": "prioritaire"}).status_code == 422
    assert run(t, params="current")["status"] == "termine"
    brands = {b for a in sched(t) if a["employee"] == "Zaki" for b in a["allocations"]}
    assert brands <= {"Cartier", "Valmont", "Ploom GVA3"} and brands  # Cellcosmet, Nuxe, GVA9, Pilar : jamais
    # une seule marque autorisée
    assert set_brands(t, "zaki", {"Cartier": "priority"}).status_code == 200
    assert run(t, params="current")["status"] == "termine"
    assert {b for a in sched(t) if a["employee"] == "Zaki" for b in a["allocations"]} <= {"Cartier"}
    assert t["p"].get(f"/periods/{t['pid']}/compatibility").json()["hard"] == []


def test_reassignment_to_an_employee_without_the_brand_is_rejected(t):
    a = next(x for x in sched(t) if x["slot_key"].startswith("GVA3"))
    aziza = t["emps"]["aziza"]["id"]  # chocolat uniquement
    r = t["p"].put(f"/assignments/{a['assignment_id']}", json={"employee_id": aziza})
    assert r.status_code == 422 and "n'est pas autorisée" in r.json()["detail"]
    assert next(x for x in sched(t) if x["assignment_id"] == a["assignment_id"])["employee_id"] == a["employee_id"]


# ---------- 5. horaires par marque ----------
EXPECTED = {
    "Ploom GVA3": ["06:00-15:00", "10:00-19:00", "12:00-21:00"], "Ploom Pilar": ["06:00-15:00", "11:00-20:00"],
    "Ploom GVA9": ["07:00-16:00", "12:30-21:30"], "Cailler": ["09:00-18:00"], "Lindt": ["09:00-18:00"], "Toblerone": ["09:00-18:00"],
    "Valmont": ["08:00-17:00", "09:00-18:00", "10:00-19:00"], "Cartier": ["08:00-17:00"], "Nuxe": ["09:00-18:00"], "Cellcosmet": ["09:00-18:00"],
}


def test_schedules_are_attached_to_the_right_brand_and_site(t):
    got = t["p"].get("/brand-schedules").json()
    for brand, expected in EXPECTED.items():
        assert [f"{x['start'][:5]}-{x['end'][:5]}" for x in got[brand]] == expected, brand
    assert {x["site"] for x in got["Ploom GVA3"]} == {"GVA3"} and {x["site"] for x in got["Ploom Pilar"]} == {"Pilar"}
    assert {x["site"] for x in got["Ploom GVA9"]} == {"GVA9"} and {x["site"] for x in got["Nuxe"]} == {"Nuxe/Cellcosmet"}


def test_manual_add_proposes_only_brand_schedules_and_checks_everything(t):
    p = t["p"]
    sc = p.get("/brand-schedules").json()
    set_brands(t, "zaki", {"Cartier": "priority", "Ploom GVA9": "reinforce"})
    zaki = t["emps"]["zaki"]["id"]
    cartier = sc["Cartier"][0]["template_id"]
    gva9 = {x["start"][:5]: x["template_id"] for x in sc["Ploom GVA9"]}
    free_day = "2026-11-10"
    used = {a["day"] for a in sched(t) if a["employee"] == "Zaki"}
    day = free_day if free_day not in used else "2026-11-24"
    if day in used:
        pytest.skip("jours de test occupés")
    # un horaire d'une autre marque est refusé : Cartier n'a que 08h-17h
    bad = p.post(f"/periods/{t['pid']}/assignments", json={"employee_id": zaki, "day": day, "brand_code": "Cartier", "template_id": gva9["07:00"]})
    assert bad.status_code == 422 and "Horaires autorisés : 08:00–17:00" in bad.json()["detail"]
    # une marque non autorisée est refusée
    assert p.post(f"/periods/{t['pid']}/assignments", json={"employee_id": zaki, "day": day, "brand_code": "Nuxe", "template_id": sc["Nuxe"][0]["template_id"]}).status_code == 422
    # un jour bloqué est refusé
    set_dates(t, "zaki", [day])
    assert p.post(f"/periods/{t['pid']}/assignments", json={"employee_id": zaki, "day": day, "brand_code": "Cartier", "template_id": cartier}).status_code == 422
    set_dates(t, "zaki", [])
    ok = p.post(f"/periods/{t['pid']}/assignments", json={"employee_id": zaki, "day": day, "brand_code": "Cartier", "template_id": cartier})
    assert ok.status_code == 201, ok.text
    mine = next(a for a in sched(t) if a["assignment_id"] == ok.json()["assignment_id"])
    assert (mine["start"], mine["end"], mine["site"], mine["locked"], mine["source"]) == ("08:00:00", "17:00:00", "Cartier", True, "manual")
    assert mine["effective_minutes"] == 480 and mine["allocations"] == {"Cartier": 480}
    # pas de double affectation le même jour
    dup = p.post(f"/periods/{t['pid']}/assignments", json={"employee_id": zaki, "day": day, "brand_code": "Ploom GVA9", "template_id": gva9["07:00"]})
    assert dup.status_code == 409
    # le moteur et le vérificateur reprennent l'ajout, et la réoptimisation le conserve (verrouillé)
    assert run(t, partial=True)["status"] == "termine"
    kept = next(a for a in sched(t) if a["assignment_id"] == ok.json()["assignment_id"])
    assert kept["employee"] == "Zaki" and kept["locked"]
    assert p.get(f"/periods/{t['pid']}/conflicts").json()["hard_violations"] == []
    # suppression : refusée tant que verrouillée
    assert p.delete(f"/assignments/{kept['assignment_id']}").status_code == 409
    p.post(f"/assignments/{kept['assignment_id']}/unlock")
    assert p.delete(f"/assignments/{kept['assignment_id']}").status_code == 204
    assert not [a for a in sched(t) if a["assignment_id"] == kept["assignment_id"]]
    set_brands(t, "zaki", {"Cartier": "priority"})
