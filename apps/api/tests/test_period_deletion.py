"""Suppression d'un planning généré : droit dédié, aperçu, confirmation par mot de passe (vérifiée côté serveur, tentatives limitées),
suppression logique en une transaction, trace protégée, rien d'autre modifié. Données entièrement créées par les tests."""
import uuid

import pytest
from sqlalchemy import text

from tests.conftest import PW, make_client, register


def login(email, pw=PW):
    c = make_client()
    r = c.post("/auth/login", json={"email": email, "password": pw})
    assert r.status_code == 200, r.text
    c.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    return c


@pytest.fixture
def t():
    o = make_client()
    dom = f"del-{uuid.uuid4().hex[:8]}.example"
    owner = register(o, "Suppression SA", f"owner@{dom}")
    assert o.post("/catalog/sites", json={"code": "AERO", "name": "Aéroport"}).status_code == 201
    assert o.post("/catalog/brands", json={"name": "Alpha"}).status_code == 201
    assert o.post("/catalog/animations", json={"site_code": "AERO", "brand_code": "Alpha", "start": "09:00", "end": "18:00", "weekdays": [0, 1, 2, 3, 4, 5, 6],
                                               "headcount": 1, "from_month": "2026-10"}).status_code == 201
    emps = [o.post("/employees", json={"code": c, "name": c.capitalize(), "brands": {"Alpha": "priority"}}).json() for c in ("ana", "ben", "cleo")]
    pids = {}
    for y, mo in ((2026, 10), (2026, 11)):
        pid = o.post("/periods/ensure", json={"year": y, "month": mo}).json()["id"]
        assert o.post(f"/periods/{pid}/runs", json={"time_limit_s": 8}, headers={"Idempotency-Key": uuid.uuid4().hex}).status_code == 202
        pids[mo] = pid
    assert o.post(f"/periods/{pids[11]}/versions", json={"label": "avant suppression"}).status_code in (200, 201)
    return dict(o=o, dom=dom, pids=pids, emps=emps, tenant=owner.get("tenant_id"))


def sched(o, pid):
    return o.get(f"/periods/{pid}/schedule")


def test_apercu_droits_et_mot_de_passe_incorrect(t):
    o, pid, dom = t["o"], t["pids"][11], t["dom"]
    pv = o.get(f"/periods/{pid}/deletion-preview").json()
    n = len(sched(o, pid).json()["assignments"])
    assert pv["label"] == "novembre 2026" and pv["assignments"] == n > 0 and pv["versions"]["total"] >= 2 and pv["can_delete"] is True
    # droit dédié : ni un manager ni un planificateur
    for role in ("manager", "planner"):
        assert o.post("/users", json={"email": f"{role}@{dom}", "name": role.capitalize(), "role": role, "password": PW}).status_code == 201
        c = login(f"{role}@{dom}")
        assert c.get(f"/periods/{pid}/deletion-preview").status_code == 403
        assert c.post(f"/periods/{pid}/delete", json={"password": PW}).status_code == 403
    # mot de passe incorrect : erreur, planning intact ; jamais conservé
    r = o.post(f"/periods/{pid}/delete", json={"password": "pas-le-bon"})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "wrong_password"
    assert len(sched(o, pid).json()["assignments"]) == n
    assert "pas-le-bon" not in str(o.get("/history").json()) and "pas-le-bon" not in str(o.get(f"/periods/{pid}/deletion-preview").json())
    # « Annuler » côté écran = aucun appel de suppression : rien ne change tant que la confirmation n'est pas envoyée
    assert o.get("/periods").status_code == 200 and any(p["id"] == pid for p in o.get("/periods").json())


def test_tentatives_repetees_bloquees(t):
    o, pid = t["o"], t["pids"][11]
    for _ in range(5):
        assert o.post(f"/periods/{pid}/delete", json={"password": "faux"}).status_code == 403
    r = o.post(f"/periods/{pid}/delete", json={"password": PW})  # même le bon mot de passe est refusé pendant le blocage
    assert r.status_code == 429 and r.json()["detail"]["code"] == "too_many_attempts"
    assert sched(o, pid).status_code == 200


def test_suppression_reussie_trace_persistante_et_rien_d_autre_modifie(t):
    o, pids, emps = t["o"], t["pids"], t["emps"]
    pid = pids[11]
    n = len(sched(o, pid).json()["assignments"])
    oct_before = sorted((a["assignment_id"], a["employee_id"]) for a in sched(o, pids[10]).json()["assignments"])
    emps_before = o.get("/employees").json()
    me = o.get("/auth/me").json()
    r = o.post(f"/periods/{pid}/delete", json={"password": PW})
    assert r.status_code == 200, r.text
    assert r.json()["message"] == "Le planning de novembre 2026 a été supprimé avec succès." and r.json()["assignments"] == n
    # retiré des vues actives, sans recréation automatique
    assert all(p["id"] != pid for p in o.get("/periods").json())
    assert sched(o, pid).status_code == 404 and o.get(f"/periods/{pid}/versions").status_code == 404
    cal = o.get("/calendar?year=2026&month=11")
    assert cal.status_code == 200 and all(p["id"] != pid for p in o.get("/periods").json())
    assert not any(p["start_date"] == "2026-11-01" for p in o.get("/periods").json())  # aucun planning recréé pour novembre
    # double soumission
    again = o.post(f"/periods/{pid}/delete", json={"password": PW})
    assert again.status_code == 409 and again.json()["detail"]["code"] == "already_deleted"
    # rien d'autre modifié
    assert sorted((a["assignment_id"], a["employee_id"]) for a in sched(o, pids[10]).json()["assignments"]) == oct_before
    assert o.get("/employees").json() == emps_before
    # trace : action, planning, date et heure, nom et identifiant interne, nombre d'affectations — consultable après la suppression
    ev = o.get("/history", params={"kind": "deletion"}).json()["items"]
    assert len(ev) == 1
    e = ev[0]
    assert e["title"] == "Suppression d'un planning" and e["period"].startswith("Novembre 2026 (planning supprimé le ") and e["by"] == me["name"]
    assert f"{n} affectation(s)" in e["lines"][0] and me["id"] in e["lines"][1] and me["name"] in e["lines"][1] and e["at_label"]
    assert o.get("/history", params={"period_id": pid}).json()["items"]  # l'historique du planning supprimé reste consultable
    # un nouveau planning de novembre peut être créé EXPLICITEMENT, distinct de l'ancien
    new = o.post("/periods/ensure", json={"year": 2026, "month": 11}).json()["id"]
    assert new != pid and sched(o, new).json()["assignments"] == []
    assert emps  # fiches inchangées (vérifié ci-dessus)


def test_trace_protegee_en_base(t):
    o, pid, tenant = t["o"], t["pids"][11], t["tenant"]
    assert o.post(f"/periods/{pid}/delete", json={"password": PW}).status_code == 200
    from app.db import tenant_session
    tid = tenant or o.get("/auth/me").json()["tenant_id"]
    with pytest.raises(Exception):
        with tenant_session(tid) as db:
            db.execute(text("DELETE FROM planning_periods WHERE id = :p"), {"p": pid})
    with pytest.raises(Exception):
        with tenant_session(tid) as db:
            db.execute(text("UPDATE planning_periods SET deleted_at = NULL WHERE id = :p"), {"p": pid})
    with pytest.raises(Exception):
        with tenant_session(tid) as db:
            db.execute(text("DELETE FROM audit_logs WHERE action = 'period.deleted'"))
    assert o.get("/history", params={"kind": "deletion"}).json()["items"]  # toujours là


def test_cloisonnement_compte_externe_et_heures_reelles(t):
    o, pid, dom, pids = t["o"], t["pids"][11], t["dom"], t["pids"]
    other = make_client()
    register(other, "Autre SA", f"autre-{uuid.uuid4().hex[:6]}@example.com")
    assert other.post(f"/periods/{pid}/delete", json={"password": PW}).status_code == 404  # autre entreprise : invisible
    # compte sans mot de passe local (connexion externe) : réauthentification demandée, rien de supprimé
    assert o.post("/users", json={"email": f"ext@{dom}", "name": "Externe", "role": "admin", "password": PW}).status_code == 201
    ext = login(f"ext@{dom}")
    from app.db import tenant_session
    with tenant_session(o.get("/auth/me").json()["tenant_id"]) as db:
        # aucune connexion externe n'existe aujourd'hui (mot de passe local obligatoire) : compte externe simulé par une empreinte vide
        db.execute(text("UPDATE users SET password_hash = '' WHERE email = :e"), {"e": f"ext@{dom}"})
    r = ext.post(f"/periods/{pid}/delete", json={"password": "quelconque"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "reauth_required"
    assert sched(o, pid).status_code == 200
    # heures réelles saisies : suppression refusée (elles ne seraient plus rattachées à rien)
    a = sched(o, pids[10]).json()["assignments"][0]
    assert o.put(f"/shifts/{a['shift_id']}/time-entry", json={"status": "worked", "actual_start": "09:00", "actual_end": "18:00", "actual_break_minutes": 60}).status_code == 200
    pv = o.get(f"/periods/{pids[10]}/deletion-preview").json()
    assert pv["can_delete"] is False and "heures réelles" in pv["blocking"][0]
    r = o.post(f"/periods/{pids[10]}/delete", json={"password": PW})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "blocked" and sched(o, pids[10]).status_code == 200


def test_nouveau_planning_du_meme_mois_apres_suppression_identite_distincte(t):
    """Après suppression, un nouveau planning de novembre se génère normalement : nouvel identifiant, l'ancien reste supprimé (jamais
    réactivé), son archive et son historique restent intacts et séparés de ceux du nouveau."""
    o, pid = t["o"], t["pids"][11]
    old_assign = sorted((a["shift_id"], a["employee_id"]) for a in sched(o, pid).json()["assignments"])
    assert o.post(f"/periods/{pid}/delete", json={"password": PW}).status_code == 200
    old_hist = o.get("/history", params={"period_id": pid, "limit": 200}).json()["items"]
    assert {i["kind"] for i in old_hist} >= {"generation", "deletion"}
    from app.db import tenant_session
    from app import models as m
    tid = o.get("/auth/me").json()["tenant_id"]
    with tenant_session(tid) as db:
        archive_before = db.get(m.PlanningPeriod, uuid.UUID(pid)).deletion_archive
    # nouveau planning du même mois, créé explicitement puis généré
    new = o.post("/periods/ensure", json={"year": 2026, "month": 11}).json()
    assert new["created"] is True and new["id"] != pid and new["name"] == "Novembre 2026"
    r = o.post(f"/periods/{new['id']}/runs", json={"time_limit_s": 8}, headers={"Idempotency-Key": uuid.uuid4().hex})
    assert r.status_code == 202
    run = o.get(f"/runs/{r.json()['run_id']}").json()
    assert run["status"] == "termine" and run["save"]["outcome"] == "replaced"
    assert run["save"]["before"] == {"assignments": 0, "locked": 0, "version": None}  # rien de l'ancien planning n'est repris
    new_rows = sched(o, new["id"]).json()["assignments"]
    assert new_rows and all(a["shift_id"] not in {x for x, _ in old_assign} for a in new_rows)  # shifts distincts
    vs = o.get(f"/periods/{new['id']}/versions").json()
    assert vs and min(v["number"] for v in vs) == 1  # numérotation propre au nouveau planning
    # l'ancien reste supprimé, inaccessible, avec son archive inchangée ; la liste n'a qu'un seul novembre (le nouveau)
    assert sched(o, pid).status_code == 404
    nov = [p for p in o.get("/periods").json() if p["start_date"] == "2026-11-01"]
    assert [p["id"] for p in nov] == [new["id"]]
    with tenant_session(tid) as db:
        old = db.get(m.PlanningPeriod, uuid.UUID(pid))
        assert old.deleted_at is not None and old.deletion_archive == archive_before
        assert len(old.deletion_archive["assignments"]) == len(old_assign)
    # historiques séparés : l'ancien inchangé, le nouveau ne contient que ses propres événements
    assert [i["id"] for i in o.get("/history", params={"period_id": pid, "limit": 200}).json()["items"]] == [i["id"] for i in old_hist]
    new_hist = o.get("/history", params={"period_id": new["id"]}).json()["items"]
    assert new_hist and all(i["period"] == "Novembre 2026" for i in new_hist) and not any(i["kind"] == "deletion" for i in new_hist)
    assert all(i["period"].startswith("Novembre 2026 (planning supprimé le ") for i in old_hist)


def test_brouillon_jamais_genere_supprime_avec_trace_et_recreable(t):
    """Brouillon sans affectation ni calcul : même fenêtre (statut), même mot de passe, même suppression logique, même trace."""
    o = t["o"]
    draft = o.post("/periods/ensure", json={"year": 2027, "month": 1}).json()
    pv = o.get(f"/periods/{draft['id']}/deletion-preview").json()
    assert (pv["label"], pv["status"], pv["status_label"], pv["assignments"], pv["can_delete"]) == ("janvier 2027", "draft", "Brouillon", 0, True)
    assert o.post(f"/periods/{draft['id']}/delete", json={"password": "faux"}).status_code == 403
    r = o.post(f"/periods/{draft['id']}/delete", json={"password": PW})
    assert r.status_code == 200 and r.json()["message"] == "Le planning de janvier 2027 a été supprimé avec succès."
    assert all(p["id"] != draft["id"] for p in o.get("/periods").json())
    # un ancien onglet qui enregistre encore : refusé, rien n'est recréé
    assert o.put(f"/periods/{draft['id']}/roster", json={"employees": []}).status_code == 404
    assert o.put(f"/periods/{draft['id']}/brands/Alpha", json={"budget_minutes": 600}).status_code == 404
    assert not any(p["start_date"] == "2027-01-01" for p in o.get("/periods").json())
    ev = next(i for i in o.get("/history", params={"kind": "deletion"}).json()["items"] if i["period_id"] == draft["id"])
    me = o.get("/auth/me").json()
    assert "(brouillon) supprimé : 0 affectation(s)" in ev["lines"][0] and me["id"] in ev["lines"][1] and ev["at_label"]
    again = o.post("/periods/ensure", json={"year": 2027, "month": 1}).json()  # recréation volontaire : identité distincte
    assert again["created"] is True and again["id"] != draft["id"]


def _rows(o, pid):
    return sorted((a["day"], a["start"], a["end"], a["site"], a["employee_id"], bool(a["locked"])) for a in sched(o, pid).json()["assignments"])


def test_recuperation_controlee_depuis_l_archive(t):
    """Récupération d'un planning supprimé : essai à blanc sans effet, mêmes droits et même mot de passe que la suppression ; un NOUVEAU
    planning reprend les affectations archivées ; le planning supprimé, son archive et la trace restent inchangés ; aucun autre mois touché."""
    o, pids, dom = t["o"], t["pids"], t["dom"]
    pid = pids[11]
    assert o.post("/catalog/sites", json={"code": "GARE", "name": "Gare"}).status_code == 201
    assert o.put(f"/periods/{pid}/sites/GARE", json={"active": False}).status_code == 200  # réglage propre au mois, repris à l'identique
    first = sched(o, pid).json()["assignments"][0]
    assert o.post(f"/assignments/{first['assignment_id']}/lock").status_code in (200, 204)  # une affectation verrouillée reste verrouillée
    before = _rows(o, pid)
    oct_before = _rows(o, pids[10])
    assert o.post(f"/periods/{pid}/delete", json={"password": PW}).status_code == 200
    from app.db import tenant_session
    from app import models as m
    tid = o.get("/auth/me").json()["tenant_id"]
    with tenant_session(tid) as db:
        archive_before = db.get(m.PlanningPeriod, uuid.UUID(pid)).deletion_archive
    periods_before = o.get("/periods").json()
    hist_before = [i["id"] for i in o.get("/history", params={"limit": 200}).json()["items"]]
    # essai à blanc : rien n'est créé, rien n'est journalisé
    pv = o.get(f"/periods/{pid}/recovery-preview").json()
    assert pv["can_recover"] is True and pv["archived"] == len(before) == pv["restorable"] and pv["archived_locked"] == 1 and pv["missing_employees"] == []
    assert o.get("/periods").json() == periods_before
    assert [i["id"] for i in o.get("/history", params={"limit": 200}).json()["items"]] == hist_before
    # mêmes protections que la suppression
    for role in ("manager", "planner"):
        assert o.post("/users", json={"email": f"{role}@{dom}", "name": role.capitalize(), "role": role, "password": PW}).status_code == 201
        c = login(f"{role}@{dom}")
        assert c.get(f"/periods/{pid}/recovery-preview").status_code == 403 and c.post(f"/periods/{pid}/recover", json={"password": PW}).status_code == 403
    bad = o.post(f"/periods/{pid}/recover", json={"password": "pas-le-bon"})
    assert bad.status_code == 403 and bad.json()["detail"]["code"] == "wrong_password" and o.get("/periods").json() == periods_before
    assert o.post(f"/periods/{pids[10]}/recover", json={"password": PW}).json()["detail"]["code"] == "not_deleted"
    # récupération
    r = o.post(f"/periods/{pid}/recover", json={"password": PW})
    assert r.status_code == 200, r.text
    new = r.json()["period_id"]
    assert new != pid and r.json()["restored"] == len(before)
    assert _rows(o, new) == before  # mêmes jours, horaires, sites, collaborateurs et verrous
    with tenant_session(tid) as db:
        assert [(x.site_code, x.active) for x in db.query(m.PeriodSite).filter(m.PeriodSite.period_id == uuid.UUID(new))] == [("GARE", False)]
    assert _rows(o, pids[10]) == oct_before  # autre mois intact
    assert [p["id"] for p in o.get("/periods").json() if p["start_date"] == "2026-11-01"] == [new]
    assert not any(v["state"] == "published" for v in o.get(f"/periods/{new}/versions").json())  # rien n'est publié
    # l'ancien reste supprimé, son archive et sa trace inchangées
    assert sched(o, pid).status_code == 404
    with tenant_session(tid) as db:
        old = db.get(m.PlanningPeriod, uuid.UUID(pid))
        assert old.deleted_at is not None and old.deletion_archive == archive_before
    ev = o.get("/history", params={"kind": "deletion"}).json()["items"]
    assert [e["action"] for e in ev] == ["period.recovered", "period.deleted"]
    assert ev[0]["title"] == "Récupération d'un planning supprimé" and f"{len(before)} affectation(s) sur {len(before)}" in ev[0]["lines"][0] and ev[0]["period_id"] == new
    # une seconde récupération est refusée : le mois a déjà un planning actif
    again = o.get(f"/periods/{pid}/recovery-preview").json()
    assert again["can_recover"] is False and "déjà un planning actif" in again["blocking"][0]
    assert o.post(f"/periods/{pid}/recover", json={"password": PW}).status_code == 409
    assert [p["id"] for p in o.get("/periods").json() if p["start_date"] == "2026-11-01"] == [new]


def test_calcul_termine_apres_la_suppression_n_ecrit_rien(t, monkeypatch):
    """Défaut constaté le 19/11 : un calcul terminé après la suppression de son planning y avait écrit 196 affectations. Désormais rien
    n'est écrit (verrou du planning à l'enregistrement), la raison est donnée, et la base refuse toute écriture dans un planning supprimé."""
    import app.optimize as opt
    from datetime import datetime, timezone
    from app.db import tenant_session
    from app import models as m
    o, pid = t["o"], t["pids"][11]
    tid = o.get("/auth/me").json()["tenant_id"]
    real = opt.solve

    def deleted_during_search(inp, cancel=None, on_progress=None):
        res = real(inp, cancel, on_progress)
        with tenant_session(tid) as db:  # suppression validée pendant que le moteur cherche
            p = db.get(m.PlanningPeriod, uuid.UUID(pid))
            for a in db.query(m.Assignment).filter(m.Assignment.period_id == p.id):
                db.delete(a)
            db.flush()
            for s in db.query(m.Shift).filter(m.Shift.period_id == p.id):
                db.delete(s)
            p.deleted_at, p.deletion_archive = datetime.now(timezone.utc), {"assignments": [], "counts": {}}
        return res
    monkeypatch.setattr(opt, "solve", deleted_during_search)
    r = o.post(f"/periods/{pid}/runs", json={"time_limit_s": 8}, headers={"Idempotency-Key": uuid.uuid4().hex})
    assert r.status_code == 202
    with tenant_session(tid) as db:
        assert db.query(m.Assignment).filter(m.Assignment.period_id == uuid.UUID(pid)).count() == 0
        assert db.query(m.Shift).filter(m.Shift.period_id == uuid.UUID(pid)).count() == 0
        res = db.query(m.OptimizationResult).join(m.OptimizationRun, m.OptimizationRun.id == m.OptimizationResult.run_id).filter(m.OptimizationRun.id == uuid.UUID(r.json()["run_id"])).one()
        assert res.report["save"]["reason_code"] == "period_deleted"
    # garantie en base : aucune écriture possible dans un planning supprimé
    with pytest.raises(Exception, match="Planning supprimé"):
        with tenant_session(tid) as db:
            db.execute(text("insert into shifts (id, tenant_id, period_id, slot_key, day, site_code, start_time, end_time, break_minutes, presence_minutes, effective_minutes) "
                            "values (gen_random_uuid(), :t, :p, 'X|2026-11-02', '2026-11-02', 'AERO', '09:00', '18:00', 60, 540, 480)"), {"t": tid, "p": pid})
