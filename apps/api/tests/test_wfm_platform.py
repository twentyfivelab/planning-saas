"""Plateforme WFM : clients, missions, remplaçants, réoptimisation locale, simulations, explications, versions et publication, heures
réelles, rentabilité, référentiel juridique, permissions. Données entièrement créées par les tests, jamais supposées."""
import csv
import datetime as dt
import io
import uuid

import pytest

from tests.conftest import PW, make_client, register

MONTH = "2026-10"


def login(email):
    c = make_client()
    r = c.post("/auth/login", json={"email": email, "password": PW})
    assert r.status_code == 200, r.text
    c.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    return c


def mk_user(o, role, employee_id=None):
    email = f"{role}-{uuid.uuid4().hex[:8]}@example.com"
    r = o.post("/users", json={"email": email, "name": role.capitalize(), "role": role, "password": PW, "employee_id": employee_id})
    assert r.status_code == 201, r.text
    return login(email), r.json()


def build(o):
    for code, name in (("AERO", "Aéroport"), ("CENTRE", "Centre")):
        assert o.post("/catalog/sites", json={"code": code, "name": name}).status_code == 201
    for b in ("Alpha", "Beta"):
        assert o.post("/catalog/brands", json={"name": b}).status_code == 201
    for site, brand in (("AERO", "Alpha"), ("CENTRE", "Beta")):
        r = o.post("/catalog/animations", json={"site_code": site, "brand_code": brand, "start": "09:00", "end": "18:00", "weekdays": [0, 1, 2, 3, 4, 5, 6], "headcount": 1, "from_month": MONTH})
        assert r.status_code == 201, r.text
    emps = {}
    for code, brands, w in (("ana", {"Alpha": "priority"}, 1), ("ben", {"Alpha": "priority", "Beta": "reinforce"}, 1), ("cleo", {"Beta": "priority"}, 1),
                            ("dan", {"Beta": "priority", "Alpha": "secondary"}, 1), ("eva", {"Alpha": "priority"}, 1), ("finn", {"Beta": "priority"}, 1), ("gia", {"Alpha": "reinforce"}, 0.75)):
        r = o.post("/employees", json={"code": code, "name": code.capitalize(), "brands": brands, "allocation_weight": w})
        assert r.status_code == 201, r.text
        emps[code] = r.json()
    y, mo = MONTH.split("-")
    pid = o.post("/periods/ensure", json={"year": int(y), "month": int(mo)}).json()["id"]
    return emps, pid


def run(o, pid, **body):
    """Les scénarios modifient compétences, contrats ou règles puis régénèrent : ils appliquent explicitement les paramètres actuels."""
    body.setdefault("params", "current")
    r = o.post(f"/periods/{pid}/runs", json={"time_limit_s": 8, **body}, headers={"Idempotency-Key": uuid.uuid4().hex})
    assert r.status_code == 202, r.text
    res = o.get(f"/runs/{r.json()['run_id']}").json()
    assert res["status"] == "termine", res
    return res


def sched(o, pid):
    return o.get(f"/periods/{pid}/schedule").json()["assignments"]


def mapping(o, pid):
    return {a["slot_key"]: a["employee"] for a in sched(o, pid)}


@pytest.fixture(scope="module")
def t():
    o = make_client()
    register(o, "WFM SA", f"wfm-{uuid.uuid4().hex[:8]}@example.com")
    emps, pid = build(o)
    run(o, pid)
    return dict(o=o, emps=emps, pid=pid)


def _client(o, name="Maison Dupont", **kw):
    r = o.post("/clients", json={"name": name, **kw})
    assert r.status_code == 201, r.text
    return r.json()


def _mission(o, client_id, **kw):
    body = {"client_id": client_id, "brand_code": "Alpha", "title": "Événement", "site_codes": ["AERO"], "start_date": "2026-10-12", "end_date": "2026-10-16", "weekdays": [0, 1, 2, 3, 4],
            "start_time": "10:00:00", "end_time": "19:00:00", "break_minutes": 60, "headcount": 1, "priority": 4, **kw}
    r = o.post("/missions", json=body)
    assert r.status_code == 201, r.text
    return r.json()


# ---- clients ----
def test_client_creation_liaison_marque_et_isolation_entre_entreprises(t):
    o = t["o"]
    c = _client(o, contacts=[{"name": "Mme Martin", "role": "Responsable", "email": "m@example.com"}], billing_rate_cents=6500)
    assert c["code"] == "MAISON-DUPONT" and c["contacts"][0]["name"] == "Mme Martin"
    assert o.post("/clients", json={"name": "Maison Dupont"}).status_code == 409
    r = o.put("/catalog/brands/Alpha/client", json={"client_id": c["id"], "billing_rate_cents": 7000})
    assert r.status_code == 200
    got = next(x for x in o.get("/clients").json() if x["id"] == c["id"])
    assert got["brands"] == [{"code": "Alpha", "name": "Alpha", "billing_rate_cents": 7000}]
    assert o.put("/catalog/brands/Alpha/client", json={"client_id": c["id"]}).json()["billing_rate_cents"] == 7000  # relier ne fait pas perdre le tarif
    k = o.post(f"/clients/{c['id']}/contracts", json={"reference": "2026-01", "ordered_minutes": 160 * 60, "billing_rate_cents": 6800})
    assert k.status_code == 201 and o.get("/clients").json()[0]["contracts"][0]["reference"] == "2026-01"
    assert o.post(f"/clients/{c['id']}/contracts", json={"reference": "x", "start_date": "2026-02-01", "end_date": "2026-01-01"}).status_code == 422
    # une autre entreprise ne voit ni le client ni ses données, et ne peut pas y rattacher de mission
    b = make_client()
    register(b, "Autre SA", f"autre-{uuid.uuid4().hex[:8]}@example.com")
    assert b.get("/clients").json() == []
    assert b.put(f"/clients/{c['id']}", json={"name": "Piraté"}).status_code == 404
    assert b.post(f"/clients/{c['id']}/contracts", json={"reference": "x"}).status_code == 404
    assert o.post(f"/clients/{c['id']}/archive", json={"archived": True}).json()["archived"] is True
    assert o.post(f"/clients/{c['id']}/archive", json={"archived": False}).json()["archived"] is False
    t["client"] = c["id"]


# ---- missions ----
def test_mission_brouillon_non_planifiee_puis_confirmee_et_qualifications(t):
    o, pid = t["o"], t["pid"]
    if "client" not in t:
        t["client"] = _client(o, name="Client Missions")["id"]
    assert o.post("/skills/new", json={"name": "Anglais", "code": "EN", "category": "langue"}).status_code == 201
    assert o.post("/skills/new", json={"name": "Formation luxe", "code": "LUXE", "category": "formation"}).status_code == 201
    x = _mission(o, t["client"], required_skills=["EN", "LUXE"], headcount=2, budget_minutes=40 * 60)
    assert x["status"] == "draft" and x["days"] == 5 and x["shifts_needed"] == 10 and x["minutes_needed"] == 10 * 480
    run(o, pid)
    assert not [a for a in sched(o, pid) if a["slot_key"].startswith("MSN-")]  # brouillon : rien n'est planifié
    assert o.post("/missions", json={**{k: x[k] for k in ("client_id", "brand_code", "title", "site_codes", "start_date", "end_date", "weekdays", "start_time", "end_time")}, "required_skills": ["INCONNU"]}).status_code == 422
    # éligibilité : marque autorisée mais qualification manquante
    el = o.get(f"/missions/{x['id']}/eligibility").json()
    assert el["eligible"] == 0 and "Aucun collaborateur admissible" in el["warning"]
    ana = next(e for e in el["employees"] if e["name"] == "Ana")
    assert ana["missing_skills"] == ["EN", "LUXE"] and not ana["eligible"]
    cleo = next(e for e in el["employees"] if e["name"] == "Cleo")
    assert any("n'est pas autorisée" in r for r in cleo["reasons"])
    # qualification partielle : toujours rejeté ; qualification complète : admissible
    o.put(f"/employees/{t['emps']['ana']['id']}/skills", json={"skills": [{"code": "EN"}]})
    o.put(f"/employees/{t['emps']['eva']['id']}/skills", json={"skills": [{"code": "EN"}, {"code": "LUXE"}]})
    assert {s["code"] for s in o.get(f"/employees/{t['emps']['eva']['id']}/skills").json()} == {"EN", "LUXE"}
    conf = o.post(f"/missions/{x['id']}/confirm").json()
    assert conf["status"] == "confirmed" and conf["eligibility"]["eligible"] == 1 and "1 collaborateur(s) admissible(s) pour 2" in conf["eligibility"]["warning"]
    assert o.post(f"/missions/{x['id']}/confirm").status_code == 409
    run(o, pid)
    rows = [a for a in sched(o, pid) if a["slot_key"].startswith(f"MSN-{x['code']}")]
    assert rows and {a["employee"] for a in rows} == {"Eva"}  # seule la personne qualifiée est affectée à la mission
    assert len(rows) == 5  # 1 seule personne admissible : 5 shifts couverts sur 10
    un = [u for u in o.get(f"/periods/{pid}/schedule").json()["uncovered"] if u["slot_key"].startswith(f"MSN-{x['code']}")]
    assert len(un) == 5
    assert o.get(f"/missions/{x['id']}").json()["shifts_assigned"] == 5
    t["mission"] = x


def test_mission_modification_annulation_renouvellement_sans_perte(t):
    o, pid = t["o"], t["pid"]
    x = t["mission"]
    body = {k: x[k] for k in ("client_id", "brand_code", "title", "site_codes", "start_date", "weekdays", "start_time", "end_time", "break_minutes", "headcount", "required_skills", "priority")}
    r = o.put(f"/missions/{x['id']}", json={**body, "end_date": "2026-10-14"}).json()
    assert r["impact"]["count"] > 0 and r["impact"]["assigned"] >= 1  # dates raccourcies : les shifts concernés sont signalés, pas supprimés en silence
    assert all(s["day"] > "2026-10-14" for s in r["impact"]["shifts"])
    before = len([a for a in sched(o, pid) if a["slot_key"].startswith("MSN-")])
    assert before > 0
    c = o.post(f"/missions/{x['id']}/cancel", json={"reason": "Demande du client annulée"}).json()
    assert c["status"] == "cancelled" and c["released"] == 0 and c["impact"]["count"] > 0
    assert len([a for a in sched(o, pid) if a["slot_key"].startswith("MSN-")]) == before  # annuler ne retire rien sans décision du manager
    n = o.post(f"/missions/{x['id']}/renew", json={"start_date": "2026-11-02", "end_date": "2026-11-03"}).json()
    assert n["status"] == "draft" and n["renewed_from"] == x["id"] and n["title"] == x["title"]
    assert o.put(f"/missions/{x['id']}", json={**body, "end_date": "2026-10-14"}).status_code == 409
    assert o.delete(f"/missions/{x['id']}").status_code == 409  # historique conservé
    assert o.delete(f"/missions/{n['id']}").status_code == 204
    run(o, pid)  # nouvelle génération : la mission annulée n'est plus planifiée
    assert not [u for u in o.get(f"/periods/{pid}/schedule").json()["uncovered"] if u["slot_key"].startswith("MSN-")]
    assert not [a for a in sched(o, pid) if a["slot_key"].startswith("MSN-")]


def test_mission_ponctuelle_coexiste_et_priorite_respectee(t):
    o, pid = t["o"], t["pid"]
    x = _mission(o, t.get("client") or _client(o, name="C2")["id"], title="Lancement", start_date="2026-10-19", end_date="2026-10-19", weekdays=[0], priority=5, site_codes=["AERO", "CENTRE"], brand_code="Alpha")
    o.post(f"/missions/{x['id']}/confirm")
    before = mapping(o, pid)
    run(o, pid)
    after = mapping(o, pid)
    msn = [k for k in after if k.startswith(f"MSN-{x['code']}")]
    assert len(msn) == 2  # deux sites, les deux couverts ; la couverture permanente est maintenue
    assert len([k for k in after if not k.startswith("MSN-")]) >= len([k for k in before if not k.startswith("MSN-")])
    # annulation avec retrait : le passé reste intact (shifts du 19 octobre déjà effectués), seul l'avenir est retiré
    assert o.post(f"/missions/{x['id']}/cancel", json={"release_shifts": True}).json()["released"] == 0
    assert len([k for k in mapping(o, pid) if k.startswith(f"MSN-{x['code']}")]) == 2
    run(o, pid)  # régénération : la mission annulée n'est plus planifiée
    assert not [k for k in mapping(o, pid) if k.startswith(f"MSN-{x['code']}")]
    fut = (dt.date.today().replace(day=1) + dt.timedelta(days=70)).replace(day=1)  # un mois à venir, quelle que soit la date d'exécution
    day = fut + dt.timedelta(days=(7 - fut.weekday()) % 7)  # premier lundi
    dec = o.post("/periods/ensure", json={"year": fut.year, "month": fut.month}).json()["id"]
    y = _mission(o, x["client_id"], title="Noël", start_date=day.isoformat(), end_date=day.isoformat(), weekdays=[0], priority=5)
    o.post(f"/missions/{y['id']}/confirm")
    run(o, dec)
    assert len([k for k in mapping(o, dec) if k.startswith(f"MSN-{y['code']}")]) == 1
    assert o.post(f"/missions/{y['id']}/cancel", json={"release_shifts": True}).json()["released"] == 1
    assert not [k for k in mapping(o, dec) if k.startswith(f"MSN-{y['code']}")]
    assert not [u for u in o.get(f"/periods/{dec}/schedule").json()["uncovered"] if u["slot_key"].startswith(f"MSN-{y['code']}")]
    o.delete(f"/periods/{dec}") if not sched(o, dec) else None


# ---- remplaçants et absence ----
def test_absence_remplacants_classes_et_transfert_atomique(t):
    o, pid = t["o"], t["pid"]
    run(o, pid)
    rows = sched(o, pid)
    a = next(x for x in rows if x["day"] >= "2026-10-05" and not x["locked"] and "Alpha" in x["allocations"])
    r = o.post(f"/periods/{pid}/absences", json={"employee_id": a["employee_id"], "start": a["day"], "end": a["day"], "reason": "maladie"})
    assert r.status_code == 200, r.text
    imp = r.json()
    assert imp["employee"]["id"] == a["employee_id"] and [s["day"] for s in imp["shifts"]] == [a["day"]]
    assert mapping(o, pid)[a["slot_key"]] == a["employee"]  # rien n'est retiré automatiquement
    ranked = o.get(f"/shifts/{a['shift_id']}/replacements").json()
    assert ranked["holder_name"] == a["employee"] and ranked["compatible"] >= 1
    assert all(c["name"] != a["employee"] for c in ranked["candidates"])
    ok = [c for c in ranked["candidates"] if c["status"] == "compatible"]
    assert ok[0]["score"] == 100 and ok == sorted(ok, key=lambda c: c["delta_cost"])
    assert all(set(c) >= {"brand_level_label", "minutes", "target_minutes", "available", "skills_ok", "terms", "cost_cents"} for c in ok)
    bad = next(c for c in ranked["candidates"] if c["name"] == "Cleo")  # Beta uniquement
    assert bad["status"] == "impossible" and bad["blocking"][0]["code"] == "BRAND_NOT_ELIGIBLE"
    pick = ok[0]
    done = o.post(f"/periods/{pid}/manual-assign", json={"employee_id": pick["employee_uuid"], "shift_id": a["shift_id"], "expected_from": a["employee_id"]})
    assert done.status_code == 200, done.text
    after = mapping(o, pid)
    assert after[a["slot_key"]] == pick["name"] and len(after) == len(rows)
    assert a["slot_key"] not in [x["slot_key"] for x in sched(o, pid) if x["employee"] == a["employee"]]
    o.put(f"/employees/{a['employee_id']}/unavailable-dates", json={"dates": []})


# ---- réoptimisation localisée et simulations ----
def test_reoptimisation_locale_ne_touche_que_le_perimetre_et_preserve_les_verrous(t):
    o, pid = t["o"], t["pid"]
    run(o, pid, confirm_replace=True)
    rows = sched(o, pid)
    a = next(x for x in rows if x["day"] == "2026-10-15" and not x["locked"])
    lock = next(x for x in rows if x["day"] == "2026-10-14" and x["employee"] == a["employee"]) if any(x["day"] == "2026-10-14" and x["employee"] == a["employee"] for x in rows) else next(x for x in rows if x["day"] == "2026-10-13")
    assert o.post(f"/assignments/{lock['assignment_id']}/lock").status_code == 200
    before = mapping(o, pid)
    o.put(f"/employees/{a['employee_id']}/unavailable-dates", json={"dates": ["2026-10-15"]})
    r = o.post(f"/periods/{pid}/local-reoptimize", json={"employee_id": a["employee_id"], "start": "2026-10-15", "end": "2026-10-15"})
    assert r.status_code == 202, r.text
    rid = r.json()["run_id"]
    assert mapping(o, pid) == before  # simulation : aucun changement tant qu'elle n'est pas appliquée
    sim = o.get(f"/simulations/{rid}").json()
    assert sim["status"] == "termine" and sim["hard_violations"] == 0, sim
    assert sim["metrics"]["changes"]["total"] == 1 and len(sim["changes"]) == 1 and sim["changes"][0]["slot_id"] == a["slot_key"]
    assert sim["changes"][0]["from"] == a["employee"] and sim["changes"][0]["to"] != a["employee"]
    versions0 = len(o.get(f"/periods/{pid}/versions").json())
    ap = o.post(f"/simulations/{rid}/apply")
    assert ap.status_code == 200, ap.text
    after = mapping(o, pid)
    assert {k for k in after if after[k] != before.get(k)} == {a["slot_key"]}  # seul le shift concerné a changé
    assert after[lock["slot_key"]] == lock["employee"] and next(x for x in sched(o, pid) if x["slot_key"] == lock["slot_key"])["locked"] is True
    vs = o.get(f"/periods/{pid}/versions").json()
    assert len(vs) == versions0 + 2 and vs[-2]["kind"] == "safety" and vs[-1]["kind"] == "generated"
    assert o.post(f"/simulations/{rid}/apply").status_code == 409  # jamais appliquée deux fois
    o.post(f"/assignments/{lock['assignment_id']}/unlock")
    o.put(f"/employees/{a['employee_id']}/unavailable-dates", json={"dates": []})


def test_simulations_comparables_sans_ecraser_le_planning(t):
    o, pid = t["o"], t["pid"]
    before = mapping(o, pid)
    strategies = {s["key"] for s in o.get("/simulation-strategies").json()}
    assert {"couverture", "equite", "preferences", "marques", "cout", "stabilite"} <= strategies
    assert o.post(f"/periods/{pid}/simulations", json={"strategies": ["inconnue"]}).status_code == 422
    r = o.post(f"/periods/{pid}/simulations", json={"strategies": ["equite", "stabilite"], "time_limit_s": 5})
    assert r.status_code == 202, r.text
    assert mapping(o, pid) == before
    rows = {x["strategy"]: x for x in o.get(f"/periods/{pid}/simulations").json() if x["strategy"]}
    for key in ("equite", "stabilite"):
        m_ = rows[key]["metrics"]
        assert m_["coverage_rate"] is not None and m_["total_minutes"] > 0 and "changes" in m_ and m_["gap_to_targets_minutes"] is not None
        assert m_["cost_cents"] is None  # aucun coût horaire renseigné : aucun montant inventé
    assert rows["stabilite"]["metrics"]["changes"]["total"] <= rows["equite"]["metrics"]["changes"]["total"]
    # une modification après le calcul rend la simulation obsolète : elle ne peut plus être appliquée
    a = next(x for x in sched(o, pid) if not x["locked"] and "Alpha" in x["allocations"])
    to = next(e for e in t["emps"].values() if "Alpha" in e["brands"] and e["name"] != a["employee"] and not [y for y in sched(o, pid) if y["employee"] == e["name"] and abs(int(y["day"][8:]) - int(a["day"][8:])) <= 1])
    assert o.put(f"/assignments/{a['assignment_id']}", json={"employee_id": to["id"]}).status_code == 200
    stale = next(x for x in o.get(f"/periods/{pid}/simulations").json() if x["strategy"] == "equite")
    assert stale["stale"] is True
    res = o.post(f"/simulations/{stale['run_id']}/apply")
    assert res.status_code == 409 and res.json()["detail"]["code"] == "stale"


def test_explication_d_une_affectation(t):
    o, pid = t["o"], t["pid"]
    run(o, pid, confirm_replace=True)
    a = next(x for x in sched(o, pid) if x["source"] == "solver")
    ex = o.get(f"/assignments/{a['assignment_id']}/explain").json()
    assert ex["employee"] == a["employee"] and ex["all_rules_ok"] is True
    assert {"BRAND", "AVAILABLE", "REST", "CONSECUTIVE"} <= {c["code"] for c in ex["checks"]}
    assert ex["origin"]["source"] == "solver" and ex["origin"]["run_status"] and "proved_optimal" in ex["origin"] and ex["origin"]["levels"]
    assert "cause unique" in ex["caveat"] and ex["observed"]
    assert ex["alternatives"] == sorted(ex["alternatives"], key=lambda x: x["extra_cost"])


# ---- versions, validation, publication ----
def test_cycle_de_vie_publication_notifications_et_restauration(t):
    o, pid = t["o"], t["pid"]
    run(o, pid, confirm_replace=True)
    v = o.post(f"/periods/{pid}/versions", json={"label": "Brouillon initial"}).json()
    assert v["exploratory"] is True and v["state"] == "snapshot"
    assert "CONTRACT" in str(o.get(f"/runs/{o.get('/runs').json()[0]['id']}/diagnostic").json()["report"]["missing_data"])
    assert o.post(f"/versions/{v['id']}/publish").status_code == 409  # contrats manquants : publication refusée
    for e in t["emps"].values():
        assert o.post("/contracts", json={"employee_id": e["id"], "weekly_minutes": 2400, "hourly_cost_cents": 3000, "monthly_target_minutes": 8000}).status_code == 201
    run(o, pid, confirm_replace=True)
    period = lambda: next(p for p in o.get("/periods").json() if p["id"] == pid)  # noqa: E731
    assert period()["status"] == "generated"
    v = o.post(f"/periods/{pid}/versions", json={"label": "Décembre — planning généré"}).json()
    assert v["exploratory"] is False
    assert o.post(f"/versions/{v['id']}/submit").json()["state"] == "in_review"
    assert period()["status"] == "in_review"
    planner, _ = mk_user(o, "planner")
    assert planner.post(f"/versions/{v['id']}/validate").status_code == 403
    assert planner.post(f"/versions/{v['id']}/publish").status_code == 403
    assert o.post(f"/versions/{v['id']}/validate").json()["state"] == "validated"
    assert period()["status"] == "validated" and period()["status_label"] == "Validé"
    # collaborateur lié à une fiche : voit uniquement ce qui est publié
    holder = sched(o, pid)[0]
    emp_client, _ = mk_user(o, "employee", holder["employee_id"])
    assert emp_client.get("/me/planning").json()["periods"] == []  # rien de publié : le planning en préparation reste invisible
    assert emp_client.get(f"/periods/{pid}/schedule").status_code == 403
    assert emp_client.get("/employees").status_code == 403
    pub = o.post(f"/versions/{v['id']}/publish").json()
    assert pub["state"] == "published" and pub["notifications"] == 1
    assert period()["status"] == "published" and period()["changed_since"] is False
    mine = emp_client.get("/me/planning").json()
    assert mine["linked"] and mine["periods"][0]["shifts"] and all("employee" not in s for s in mine["periods"][0]["shifts"])
    notes = emp_client.get("/notifications").json()
    assert notes["unread"] == 1 and "Nouveau planning disponible" in notes["items"][0]["title"]
    assert emp_client.post(f"/notifications/{notes['items'][0]['id']}/read").json()["read"] is True
    assert emp_client.get("/notifications").json()["unread"] == 0
    assert o.get("/notifications").json()["unread"] == 0  # jamais les notifications d'un autre
    # une génération ne remplace jamais silencieusement un planning publié
    r = o.post(f"/periods/{pid}/runs", json={"time_limit_s": 5}, headers={"Idempotency-Key": uuid.uuid4().hex})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "official_version"
    # plusieurs modifications : une seule notification à la publication suivante
    moves = 0
    rows = sched(o, pid)
    for a in [x for x in rows if x["employee_id"] == holder["employee_id"] and not x["locked"]][:3]:
        cands = o.get(f"/shifts/{a['shift_id']}/replacements").json()["candidates"]
        pick = next((c for c in cands if c["status"] == "compatible"), None)
        if pick and o.put(f"/assignments/{a['assignment_id']}", json={"employee_id": pick["employee_uuid"]}).status_code == 200:
            moves += 1
    assert moves >= 1
    assert period()["changed_since"] is True and period()["status"] == "published"
    assert o.post(f"/versions/{v['id']}/validate").status_code == 409
    current = mapping(o, pid)
    assert current != {x["slot_key"]: x["employee"] for x in rows}
    v2 = o.post(f"/periods/{pid}/versions", json={"label": "Planning corrigé"}).json()
    pub2 = o.post(f"/versions/{v2['id']}/publish").json()
    assert pub2["state"] == "published"
    notes = emp_client.get("/notifications").json()
    assert notes["unread"] == 1 and "a changé" in notes["items"][0]["title"] and "retiré" in notes["items"][0]["body"]
    states = {x["id"]: x["state"] for x in o.get(f"/periods/{pid}/versions").json()}
    assert states[v["id"]] == "superseded" and states[v2["id"]] == "published"
    assert o.post(f"/versions/{v['id']}/publish").status_code == 409
    snap_before = {x["slot_key"]: x["employee"] for x in rows}
    # restauration : retour à la première version publiée, elle-même réversible
    back = o.post(f"/versions/{v['id']}/restore").json()
    assert back["changed"] >= 1 and back["safety_version"] > v2["number"]
    assert mapping(o, pid) == snap_before
    assert o.post(f"/versions/{back['safety_version'] and next(x['id'] for x in o.get(f'/periods/{pid}/versions').json() if x['number'] == back['safety_version'])}/restore").status_code == 200
    assert mapping(o, pid) == current
    actions = {a["action"] for a in o.get("/audit").json()}
    assert {"version.publish", "version.validate", "version.restore"} <= actions


# ---- heures réelles et rentabilité ----
def test_heures_reelles_distinctes_du_planning(t):
    o, pid = t["o"], t["pid"]
    before = sched(o, pid)
    a = next(x for x in before if x["day"] == "2026-10-20")
    r = o.put(f"/shifts/{a['shift_id']}/time-entry", json={"status": "worked", "actual_start": "09:20", "actual_end": "18:45", "actual_break_minutes": 60, "note": "retard train"})
    assert r.status_code == 200, r.text
    e = r.json()
    assert e["late_minutes"] == 20 and e["worked_minutes"] == 505 and e["overtime_minutes"] == 25 and e["validated"] is False
    assert sched(o, pid) == before  # le planning prévisionnel n'est jamais modifié
    # validation : pas par la personne concernée
    self_mgr, _ = mk_user(o, "manager", a["employee_id"])
    assert self_mgr.post(f"/time-entries/{e['id']}/validate").status_code == 403
    assert o.post(f"/time-entries/{e['id']}/validate").json()["validated"] is True
    # modifier une saisie validée retire la validation
    e2 = o.put(f"/shifts/{a['shift_id']}/time-entry", json={"status": "worked", "actual_start": "09:00", "actual_end": "18:00", "actual_break_minutes": 60}).json()
    assert e2["validated"] is False and e2["late_minutes"] == 0 and e2["overtime_minutes"] == 0
    o.post(f"/time-entries/{e2['id']}/validate")
    b = next(x for x in before if x["day"] == "2026-10-21")
    ab = o.put(f"/shifts/{b['shift_id']}/time-entry", json={"status": "absent", "absence_reason": "maladie"}).json()
    assert ab["worked_minutes"] == 0 and ab["status"] == "absent"
    assert o.put(f"/shifts/{b['shift_id']}/time-entry", json={"status": "worked"}).status_code == 422
    rows = o.get(f"/periods/{pid}/time-entries", params={"day": "2026-10-20"}).json()
    assert len(rows["rows"]) >= 1 and rows["rows"][0]["planned_minutes"] > 0
    assert rows["summary"]["to_validate"] >= 1
    planner, _ = mk_user(o, "planner")
    assert planner.post(f"/time-entries/{e['id']}/validate").status_code == 403
    t["time_shift"] = a


def test_rentabilite_calculs_exacts_et_jamais_inventes(t):
    o = t["o"]
    rep = o.get("/reports/finance", params={"month": MONTH}).json()
    beta = next(r for r in rep["by_brand"] if r["code"] == "Beta") if rep["by_brand"] and "code" in rep["by_brand"][0] else next(r for r in rep["by_brand"] if r["key"] == "Beta")
    alpha = next(r for r in rep["by_brand"] if r["key"] == "Alpha")
    # Alpha a un tarif (70 CHF/h) ; Beta n'a aucun tarif : aucun montant n'est inventé
    assert beta["billable_planned_cents"] is None and beta["bill_missing_minutes"] == beta["planned_minutes"] > 0 and beta["margin_planned_cents"] is None
    assert alpha["billable_planned_cents"] == round(alpha["planned_minutes"] * 7000 / 60)
    assert alpha["cost_planned_cents"] == round(alpha["planned_minutes"] * 3000 / 60)
    assert alpha["margin_planned_cents"] == alpha["billable_planned_cents"] - alpha["cost_planned_cents"]
    assert alpha["actual_minutes"] >= 480 and alpha["client"]
    # sans permission financière : les heures restent visibles, jamais les montants
    planner, _ = mk_user(o, "planner")
    hidden = planner.get("/reports/finance", params={"month": MONTH}).json()
    assert hidden["see_money"] is False and all(r["cost_planned_cents"] is None and r["margin_planned_cents"] is None for r in hidden["by_brand"])
    assert hidden["by_brand"][0]["planned_minutes"] > 0
    assert planner.get("/reports/billing.csv", params={"month": MONTH}).status_code == 403
    pay = list(csv.reader(io.StringIO(o.get("/reports/payroll.csv", params={"month": MONTH}).text), delimiter=";"))
    assert pay[0][:3] == ["Code", "Collaborateur", "Heures planifiées"] and len(pay) > 2
    bill = list(csv.reader(io.StringIO(o.get("/reports/billing.csv", params={"month": MONTH}).text), delimiter=";"))
    row = next(r for r in bill if r[1] == "Beta")
    assert row[5] == "" and row[7] == "oui"
    cov = list(csv.reader(io.StringIO(o.get("/reports/coverage.csv", params={"month": MONTH}).text), delimiter=";"))
    assert cov[0][5] == "État" and any(r[5] == "couvert" for r in cov[1:])


def test_tableau_de_bord(t):
    o, pid = t["o"], t["pid"]
    d = o.get(f"/periods/{pid}/dashboard", params={"day": "2026-10-20"}).json()
    assert d["people"]["active"] == 7 and d["planning"]["coverage_rate"] is not None
    assert d["people"]["working_today"] + d["people"]["available_today"] + d["people"]["unavailable_today"] == 7
    assert d["brands"] and d["sites"][0]["name"] in ("Aéroport", "Centre") and d["equity"]["employees"]
    assert d["finance"]["cost_planned_cents"] is not None and d["finance"]["planned_minutes"] > 0


# ---- référentiel juridique ----
def test_referentiel_juridique_versionne_et_execute_par_le_moteur():
    o = make_client()
    register(o, "Légal SA", f"legal-{uuid.uuid4().hex[:8]}@example.com")
    emps, pid = build(o)
    lib = o.get("/legal/rules").json()
    keys = {x["key"]: x for x in lib["templates"]}
    assert {"rest_11h", "weekly_45h", "weekly_50h", "breaks_art15"} <= set(keys) and all(x["source_url"].startswith("https://www.seco.admin.ch/") for x in keys.values())
    assert not keys["weekly_45h"]["active"]  # rien n'est activé d'office
    # plafond hebdomadaire : par régime du contrat
    r = o.post("/legal/rules", json={"code": "weekly_max_minutes", "jurisdiction": "TEST-16H", "params": {"value": 16 * 60}})
    assert r.status_code == 201, r.text
    assert r.json()["review_status"] == "a_valider" and r.json()["version"] == 1
    for code in ("ana", "ben", "eva"):
        o.post("/contracts", json={"employee_id": emps[code]["id"], "legal_regime": "TEST-16H"})
    run(o, pid)
    per_week = {}
    for a in sched(o, pid):
        if a["employee"] in ("Ana", "Ben", "Eva"):
            wk = dt.date.fromisoformat(a["day"]).isocalendar()[:2]
            per_week[a["employee"], wk] = per_week.get((a["employee"], wk), 0) + a["effective_minutes"]
    assert per_week and max(per_week.values()) <= 16 * 60
    assert o.get(f"/periods/{pid}/conflicts").json()["hard_violations"] == []
    # nouvelle version : l'ancienne reste dans l'historique, la nouvelle repart à valider
    v2 = o.post("/legal/rules", json={"code": "weekly_max_minutes", "jurisdiction": "TEST-16H", "params": {"value": 24 * 60}, "valid_from": "2027-01-01"}).json()
    assert v2["version"] == 2
    rows = [x for x in o.get("/legal/rules").json()["rules"] if x["jurisdiction"] == "TEST-16H"]
    assert [x["version"] for x in rows] == [1, 2] and rows[0]["valid_to"] == "2026-12-31"
    # validation réservée, nominative et tracée
    planner, _ = mk_user(o, "planner")
    assert planner.post(f"/legal/rules/{v2['id']}/review", json={"status": "valide"}).status_code == 403
    done = o.post(f"/legal/rules/{v2['id']}/review", json={"status": "valide", "note": "Vu par le juriste"}).json()
    assert done["review_status"] == "valide" and done["reviewed_by"]
    assert o.post("/legal/rules", json={"code": "weekly_max_minutes", "params": {"value": -5}}).status_code == 422
    # pauses : un shift à la pause trop courte n'est pas pourvu et le diagnostic le dit
    assert o.post("/legal/rules/from-template", json={"template": "breaks_art15"}).status_code == 201
    assert o.post("/legal/rules/from-template", json={"template": "breaks_art15"}).status_code == 409
    o.post("/catalog/animations", json={"site_code": "AERO", "brand_code": "Alpha", "start": "08:00", "end": "17:00", "break_minutes": 15, "weekdays": [0], "headcount": 1, "from_month": MONTH})
    res = run(o, pid)
    report = o.get(f"/runs/{res['id']}/diagnostic").json()["report"]
    assert any(i["code"] == "BREAK_RULE" for i in report["missing_data"])
    assert not [a for a in sched(o, pid) if a["start"] == "08:00:00"]
    assert o.get(f"/periods/{pid}/conflicts").json()["hard_violations"] == []


# ---- relations, préférences, permissions ----
def test_relations_et_preferences_generalisees_sans_nom_dans_le_code():
    o = make_client()
    register(o, "Rel SA", f"rel-{uuid.uuid4().hex[:8]}@example.com")
    emps, pid = build(o)
    assert o.post("/relationship-preferences", json={"employee_id": emps["ana"]["id"], "other_employee_id": emps["ana"]["id"], "kind": "avoid_together"}).status_code == 422
    assert o.post("/relationship-preferences", json={"employee_id": emps["ana"]["id"], "other_employee_id": emps["ben"]["id"], "kind": "work_together", "strict": True}).status_code == 422
    assert o.post("/relationship-preferences", json={"employee_id": emps["ana"]["id"], "other_employee_id": emps["ben"]["id"], "kind": "avoid_together", "strict": True}).status_code == 201
    # jour de repos obligatoire et site autorisé strict
    assert o.post("/employee-preferences", json={"employee_id": emps["eva"]["id"], "kind": "rest_weekdays", "params": {"weekdays": [0]}, "is_hard": True}).status_code == 201
    assert o.post("/employee-preferences", json={"employee_id": emps["ben"]["id"], "kind": "sites", "params": {"sites": ["AERO"]}, "is_hard": True}).status_code == 201
    run(o, pid)
    rows = sched(o, pid)
    assert not [a for a in rows if a["employee"] == "Eva" and dt.date.fromisoformat(a["day"]).weekday() == 0]
    assert not [a for a in rows if a["employee"] == "Ben" and a["site"] != "AERO"]
    ana = {(a["day"], a["site"]) for a in rows if a["employee"] == "Ana"}
    ben = {(a["day"], a["site"]) for a in rows if a["employee"] == "Ben"}
    assert not (ana & ben)
    assert o.get(f"/periods/{pid}/conflicts").json()["hard_violations"] == []


def test_responsable_de_marque_limite_a_son_perimetre(t):
    o, pid = t["o"], t["pid"]
    bm, user = mk_user(o, "brand_manager")
    assert o.patch(f"/users/{user['id']}", json={"scope_brands": ["Alpha"]}).status_code == 200
    rows = bm.get(f"/periods/{pid}/schedule").json()["assignments"]
    assert rows and all("Alpha" in a["allocations"] for a in rows)
    assert bm.get(f"/periods/{pid}/day-shifts", params={"day": "2026-10-20"}).status_code == 403
    assert bm.get("/employees").status_code == 403
    assert bm.put(f"/assignments/{rows[0]['assignment_id']}", json={"employee_id": rows[0]["employee_id"]}).status_code == 403
    entries = bm.get(f"/periods/{pid}/time-entries", params={"day": "2026-10-20"}).json()["rows"]
    assert all("Alpha" in r["brands"] for r in entries)
    rep = bm.get("/reports/finance", params={"month": MONTH}).json()
    assert [r["key"] for r in rep["by_brand"]] == ["Alpha"] and rep["see_money"] is False
    # valide les heures de sa marque, pas celles d'une autre
    all_rows = o.get(f"/periods/{pid}/schedule").json()["assignments"]
    beta = next(a for a in all_rows if "Beta" in a["allocations"] and a["day"] <= "2026-10-31")
    entry = o.put(f"/shifts/{beta['shift_id']}/time-entry", json={"status": "worked", "actual_start": "09:00", "actual_end": "18:00"}).json()
    assert bm.post(f"/time-entries/{entry['id']}/validate").status_code == 403


def test_securite_entetes_et_animation_sans_horaire_orphelin(t):
    o = t["o"]
    r = o.get("/health")
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY" and r.headers["cache-control"] == "no-store"
    n0 = len(o.get("/shift-templates").json())
    a = o.post("/catalog/animations", json={"site_code": "AERO", "brand_code": "Alpha", "start": "07:00", "end": "16:00", "weekdays": [1], "headcount": 1, "from_month": "2027-05"}).json()
    assert len(o.get("/shift-templates").json()) == n0 + 1
    assert o.delete(f"/catalog/animations/{a['id']}", params={"from_month": "2027-05"}).status_code == 204
    assert len(o.get("/shift-templates").json()) == n0  # supprimer une animation ne laisse pas d'horaire orphelin


def test_suppression_reservee_a_ce_qui_n_a_rien_planifie(t):
    o = t["o"]
    c = _client(o, name="Client éphémère")
    n0 = len(o.get("/shift-templates").json())
    x = _mission(o, c["id"], title="Sans shift", start_date="2027-06-07", end_date="2027-06-07", weekdays=[0])
    assert o.post(f"/missions/{x['id']}/confirm").status_code == 200
    assert len(o.get("/shift-templates").json()) == n0 + 1
    assert o.delete(f"/missions/{x['id']}").status_code == 409  # confirmée : s'annule d'abord
    assert o.delete(f"/clients/{c['id']}").status_code == 409  # client avec mission : s'archive
    assert o.post(f"/missions/{x['id']}/cancel", json={}).status_code == 200
    assert o.delete(f"/missions/{x['id']}").status_code == 204  # annulée sans aucun shift
    assert len(o.get("/shift-templates").json()) == n0  # aucun horaire orphelin
    assert o.delete(f"/clients/{c['id']}").status_code == 204


def test_saisies_copies_et_simulations_retirables_seulement_si_sans_consequence(t):
    o, pid = t["o"], t["pid"]
    v = o.post(f"/periods/{pid}/versions", json={"label": "À retirer"}).json()
    assert o.delete(f"/versions/{v['id']}").status_code == 204
    generated = next(x for x in o.get(f"/periods/{pid}/versions").json() if x["kind"] == "generated")
    assert o.delete(f"/versions/{generated['id']}").status_code == 409  # une version générée reste dans l'historique
    a = next(x for x in sched(o, pid) if x["day"] == "2026-10-25")
    e = o.put(f"/shifts/{a['shift_id']}/time-entry", json={"status": "worked", "actual_start": "09:00", "actual_end": "18:00"}).json()
    o.post(f"/time-entries/{e['id']}/validate")
    assert o.delete(f"/shifts/{a['shift_id']}/time-entry").status_code == 409  # validé : protégé
    o.post(f"/time-entries/{e['id']}/unvalidate")
    assert o.delete(f"/shifts/{a['shift_id']}/time-entry").status_code == 204
    rid = o.post(f"/periods/{pid}/simulations", json={"strategies": ["couverture"], "time_limit_s": 3}).json()["runs"][0]["run_id"]
    assert o.delete(f"/simulations/{rid}").status_code == 204
    assert o.get(f"/simulations/{rid}").status_code == 404


def test_horaires_opposes_saisis_dans_un_seul_sens_et_parametres_valides():
    o = make_client()
    register(o, "Opp SA", f"opp-{uuid.uuid4().hex[:8]}@example.com")
    emps, pid = build(o)
    # saisie du collaborateur dont le code est le plus grand vers le plus petit : doit agir quand même
    assert o.post("/relationship-preferences", json={"employee_id": emps["eva"]["id"], "other_employee_id": emps["ana"]["id"], "kind": "opposite_shifts"}).status_code == 201
    res = run(o, pid)
    report = o.get(f"/runs/{res['id']}/diagnostic").json()["report"]
    assert "family" in report["objective"]
    assert o.post("/employee-preferences", json={"employee_id": emps["ana"]["id"], "kind": "rest_weekdays", "params": {"weekdays": [9]}}).status_code == 422
    assert o.post("/employee-preferences", json={"employee_id": emps["ana"]["id"], "kind": "sites", "params": {"sites": "AERO"}}).status_code == 422


def test_effacement_d_un_collaborateur_avec_heures_reelles():
    o = make_client()
    register(o, "RGPD SA", f"rgpd-{uuid.uuid4().hex[:8]}@example.com")
    emps, pid = build(o)
    run(o, pid)
    a = next(x for x in sched(o, pid) if x["day"] == "2026-10-05")
    assert o.put(f"/shifts/{a['shift_id']}/time-entry", json={"status": "worked", "actual_start": "09:00", "actual_end": "18:00"}).status_code == 200
    o.post(f"/periods/{pid}/versions", json={"label": "Avec le nom"})
    assert o.get(f"/data-subject/{a['employee_id']}").json()["time_entries"]  # droit d'accès : les heures réelles en font partie
    r = o.delete(f"/data-subject/{a['employee_id']}")
    assert r.status_code == 204, r.text
    who = next(e for e in o.get("/employees").json() if e["id"] == a["employee_id"])
    assert who["name"].startswith("Anonymisé") and who["active"] is False
    assert a["employee"] not in str(o.get(f"/periods/{pid}/schedule").json()["assignments"])
    rows = o.get(f"/periods/{pid}/time-entries", params={"day": "2026-10-05"}).json()["rows"]
    assert any(x["employee"] == who["name"] and x["entry"] for x in rows)  # les heures restent, le nom non
    vid = o.get(f"/periods/{pid}/versions").json()[-1]["id"]
    other = o.post(f"/periods/{pid}/versions", json={"label": "Après"}).json()["id"]
    assert a["employee"] not in str(o.get("/versions/compare", params={"a": vid, "b": other}).json())


# ---- vérificateur indépendant : chaque planning, quelle que soit son origine ----
def _report(o, rid):
    return o.get(f"/runs/{rid}/diagnostic").json()["report"]


@pytest.fixture()
def vt():
    o = make_client()
    register(o, "Verif SA", f"verif-{uuid.uuid4().hex[:8]}@example.com")
    emps, pid = build(o)
    return dict(o=o, emps=emps, pid=pid)


def test_verification_explicite_generation_reoptimisation_simulation_et_application(vt):
    o, pid = vt["o"], vt["pid"]
    v = _report(o, run(o, pid)["id"])["verification"]  # génération complète
    assert v["executed"] is True and v["kind"] == "full" and v["solver_result"]["violations"] == [] and v["fresh_data"]["violations"] == []
    assert v["after_save"]["checked"] > 0 and v["after_save"]["unchecked"] == 0 and v["after_save"]["violations"] == []
    r = o.post(f"/periods/{pid}/reoptimize", json={"time_limit_s": 5}, headers={"Idempotency-Key": uuid.uuid4().hex}).json()
    v = _report(o, r["run_id"])["verification"]  # réoptimisation partielle
    assert v["kind"] == "partial" and v["executed"] and v["after_save"]["violations"] == []
    a = sched(o, pid)[0]
    r = o.post(f"/periods/{pid}/local-reoptimize", json={"shift_ids": [a["shift_id"]], "time_limit_s": 3}).json()
    v = _report(o, r["run_id"])["verification"]  # réoptimisation locale, en simulation : vérifiée sans rien enregistrer
    assert v["kind"] == "local" and v["simulation"] is True and v["executed"] and "after_save" not in v
    sim = o.post(f"/periods/{pid}/simulations", json={"strategies": ["equite"], "time_limit_s": 3}).json()["runs"][0]["run_id"]
    assert _report(o, sim)["verification"]["executed"] is True
    assert o.get(f"/simulations/{sim}").json()["verified"] is True
    assert o.post(f"/simulations/{sim}/apply").status_code == 200  # l'application revérifie le planning enregistré


def test_sans_planning_produit_rien_n_est_enregistre_et_c_est_dit(vt):
    o, pid = vt["o"], vt["pid"]
    run(o, pid)
    a = sched(o, pid)[0]
    o.post(f"/assignments/{a['assignment_id']}/lock")
    o.put(f"/employees/{a['employee_id']}/unavailable-dates", json={"dates": [a["day"]]})
    before = mapping(o, pid)
    res = run(o, pid)
    assert res["result_status"] == "infaisable"
    rep = _report(o, res["id"])
    assert rep["verification"]["executed"] is False and "rien à vérifier" in rep["verification"]["reason"]
    assert any(i["code"] == "LOCK_IMPOSSIBLE" and a["employee"] in i["message"] for i in rep["diagnostics"])
    assert mapping(o, pid) == before


def test_planning_rejete_par_le_verificateur_jamais_enregistre(vt, monkeypatch):
    from planning_solver import engine
    o, pid = vt["o"], vt["pid"]
    run(o, pid)
    before, n = mapping(o, pid), len(o.get(f"/periods/{pid}/versions").json())
    monkeypatch.setattr(engine, "validate", lambda inp, a: ["FAUX: violation de test"])
    res = run_expect_error(o, pid)
    assert res["status"] == "erreur"
    assert mapping(o, pid) == before and len(o.get(f"/periods/{pid}/versions").json()) == n


def run_expect_error(o, pid):
    r = o.post(f"/periods/{pid}/runs", json={"time_limit_s": 5}, headers={"Idempotency-Key": uuid.uuid4().hex})
    return o.get(f"/runs/{r.json()['run_id']}").json()


def test_donnee_modifiee_pendant_le_calcul_le_plan_est_rejete(vt, monkeypatch):
    """Une absence saisie pendant le calcul : le plan calculé sur l'ancienne donnée n'est pas enregistré."""
    import app.optimize as opt
    from app import models as m
    from app.db import tenant_session
    o, pid = vt["o"], vt["pid"]
    run(o, pid)
    before = mapping(o, pid)
    real = opt.solve
    tid = o.get("/tenant").json()["id"]

    def solve_then_absence(inp, cancel=None, progress=None):
        res = real(inp, cancel, progress)
        a = res.assignments[0]
        code = a.employee_id
        with tenant_session(tid) as db:
            e = next(x for x in db.query(m.Employee).all() if x.code == code)
            db.add(m.Unavailability(tenant_id=e.tenant_id, employee_id=e.id, on_date=a.day, reason="absence pendant le calcul"))
        return res
    monkeypatch.setattr(opt, "solve", solve_then_absence)
    res = run_expect_error(o, pid)
    assert res["status"] == "erreur"
    rep = _report(o, res["id"])
    assert any(v.startswith("UNAVAILABLE") for v in rep["verification"]["fresh_data"]["violations"])
    assert rep["blocked_by_verification"] and mapping(o, pid) == before


def test_verification_du_planning_enregistre_annule_tout_l_enregistrement(vt, monkeypatch):
    import app.optimize as opt
    o, pid = vt["o"], vt["pid"]
    run(o, pid)
    before, n = mapping(o, pid), len(o.get(f"/periods/{pid}/versions").json())
    monkeypatch.setattr(opt, "verify_saved_plan", lambda db, p, c, b: {"checked": 1, "unchecked": 0, "violations": ["FAUX: après enregistrement"], "already_known": 0})
    res = run_expect_error(o, pid)
    assert res["status"] == "erreur"
    assert mapping(o, pid) == before and len(o.get(f"/periods/{pid}/versions").json()) == n  # ni affectation, ni copie de sécurité
    rep = _report(o, res["id"])
    assert rep["blocked_by_verification"] == ["FAUX: après enregistrement"] and rep["verification"]["after_save"]["violations"]


def test_application_d_une_simulation_annulee_si_le_planning_enregistre_viole(vt, monkeypatch):
    import app.routers.decisions as dec
    o, pid = vt["o"], vt["pid"]
    run(o, pid)
    before, n = mapping(o, pid), len(o.get(f"/periods/{pid}/versions").json())
    sim = o.post(f"/periods/{pid}/simulations", json={"strategies": ["equite"], "time_limit_s": 3}).json()["runs"][0]["run_id"]
    monkeypatch.setattr(dec, "verify_saved_plan", lambda db, p, c, b: {"checked": 1, "unchecked": 0, "violations": ["FAUX: après application"], "already_known": 0})
    r = o.post(f"/simulations/{sim}/apply")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "hard_violations"
    assert mapping(o, pid) == before and len(o.get(f"/periods/{pid}/versions").json()) == n
    assert o.get(f"/simulations/{sim}").json()["applied_at"] is None


# ---- conservation des versions et remise à zéro ----
def test_conservation_des_versions_automatiques(vt):
    o, pid = vt["o"], vt["pid"]
    assert o.get("/settings/version-retention").json()["keep_per_month"] == 20  # valeur par défaut
    planner, _ = mk_user(o, "planner")
    assert planner.put("/settings/version-retention", json={"keep_per_month": 4}).status_code == 403
    assert o.put("/settings/version-retention", json={"keep_per_month": 1}).status_code == 422  # une génération crée deux versions
    run(o, pid)
    manual = o.post(f"/periods/{pid}/versions", json={"label": "À garder"}).json()
    official = o.post(f"/periods/{pid}/versions", json={"label": "Validée"}).json()
    assert o.post(f"/versions/{official['id']}/validate").status_code == 200
    for _ in range(4):
        run(o, pid, confirm_replace=True)
    auto = lambda: [x for x in o.get(f"/periods/{pid}/versions").json() if x["kind"] in ("safety", "generated")]  # noqa: E731
    assert len(auto()) == 9  # première génération : 1 version ; les suivantes : 2 (copie de sécurité et planning généré)
    r = o.put("/settings/version-retention", json={"keep_per_month": 4, "max_age_days": None}).json()
    assert len(auto()) == 9  # enregistrer la politique ne retire rien
    assert next(x for x in r["months"] if x["period_id"] == pid)["would_remove"] == 5
    done = o.post("/settings/version-retention/apply").json()
    assert len(done["removed"][next(x["name"] for x in r["months"] if x["period_id"] == pid)]) == 5
    rows = auto()
    assert len(rows) == 4 and rows[-1]["kind"] == "generated"  # les plus récentes
    ids = {x["id"] for x in o.get(f"/periods/{pid}/versions").json()}
    assert manual["id"] in ids and official["id"] in ids  # versions manuelles et validées jamais concernées
    run(o, pid, confirm_replace=True)  # la politique s'applique aussi à chaque génération
    assert len(auto()) == 4
    assert "version.retention" in {a["action"] for a in o.get("/audit").json()}
    # âge maximal : la dernière copie reste toujours
    from app import models as m
    from app.db import tenant_session
    tid = o.get("/tenant").json()["id"]
    with tenant_session(tid) as db:
        for v in db.query(m.ScheduleVersion).filter(m.ScheduleVersion.kind.in_(("safety", "generated"))):
            v.created_at = v.created_at.replace(year=2020)
    o.put("/settings/version-retention", json={"keep_per_month": None, "max_age_days": 30})
    o.post("/settings/version-retention/apply")
    assert len(auto()) == 1
    assert o.get("/tenant").status_code == 200


def test_purge_des_copies_automatiques_et_planning_intact(vt):
    o, pid = vt["o"], vt["pid"]
    run(o, pid)
    run(o, pid)
    manual = o.post(f"/periods/{pid}/versions", json={"label": "À garder"}).json()
    before = mapping(o, pid)
    manager, _ = mk_user(o, "manager")
    assert manager.post(f"/periods/{pid}/versions/purge-automatic", json={"confirm": True}).status_code == 403
    assert o.post(f"/periods/{pid}/versions/purge-automatic", json={"confirm": False}).status_code == 422
    r = o.post(f"/periods/{pid}/versions/purge-automatic", json={"confirm": True}).json()
    assert r["removed"] == 3
    assert [x["id"] for x in o.get(f"/periods/{pid}/versions").json()] == [manual["id"]]
    assert mapping(o, pid) == before
    assert "version.purge_automatic" in {a["action"] for a in o.get("/audit").json()}


def test_remise_a_zero_d_un_mois_sans_toucher_aux_autres(vt):
    o, pid, emps = vt["o"], vt["pid"], vt["emps"]
    run(o, pid)
    oct_before = mapping(o, pid)
    nov = o.post("/periods/ensure", json={"year": 2026, "month": 11}).json()["id"]
    assert o.patch(f"/periods/{nov}/wizard", json={"step": 4}).status_code == 200
    o.put(f"/periods/{nov}/roster", json={"employees": [{"employee_id": emps["ana"]["id"], "included": False}]})
    o.put(f"/employees/{emps['ben']['id']}/month-params/2026-11", json={"max_days_set": True, "max_days_count": 3, "max_days_period": "week"})
    o.put(f"/periods/{nov}/brands/Alpha", json={"active": True, "budget_minutes": 80 * 60})
    run(o, nov)
    assert sched(o, nov)
    a = sched(o, nov)[0]
    o.put(f"/employees/{a['employee_id']}/unavailable-dates", json={"dates": ["2026-11-20"]})
    assert o.post(f"/periods/{nov}/reset", json={"confirm_name": "mauvais nom"}).status_code == 422
    manager, _ = mk_user(o, "manager")
    assert manager.post(f"/periods/{nov}/reset", json={"confirm_name": "Novembre 2026"}).status_code == 403
    r = o.post(f"/periods/{nov}/reset", json={"confirm_name": "Novembre 2026"})
    assert r.status_code == 200, r.text
    assert r.json()["removed"]["affectations"] > 0 and r.json()["removed"]["budgets"] == 1
    p = next(x for x in o.get("/periods").json() if x["id"] == nov)
    assert p["status"] == "draft" and p["assignments"] == 0 and p["wizard_step"] is None
    assert sched(o, nov) == [] and o.get(f"/periods/{nov}/schedule").json()["uncovered"] == []
    assert o.get(f"/periods/{nov}/versions").json() == []
    assert all(x["included"] for x in o.get(f"/periods/{nov}/roster").json()["employees"] if x["state"] != "inactive")
    assert not next(x for x in o.get("/month-params", params={"month": "2026-11"}).json() if x["employee_id"] == emps["ben"]["id"])["max_days_set"]
    assert next(b for b in o.get(f"/periods/{nov}/brands").json() if b["code"] == "Alpha")["budget_minutes"] is None
    assert mapping(o, pid) == oct_before  # l'autre mois n'a pas bougé
    assert o.get(f"/employees/{a['employee_id']}/availability").json()["dates"] == ["2026-11-20"]  # les fiches ne changent pas
    assert "period.reset" in {x["action"] for x in o.get("/audit").json()}
    # refusée dès qu'une version officielle existe
    for e in emps.values():
        o.post("/contracts", json={"employee_id": e["id"], "weekly_minutes": 2400})
    run(o, pid, confirm_replace=True)
    v = o.post(f"/periods/{pid}/versions", json={"label": "Officielle"}).json()
    assert o.post(f"/versions/{v['id']}/validate").status_code == 200
    assert o.post(f"/periods/{pid}/reset", json={"confirm_name": "Octobre 2026"}).status_code == 409
