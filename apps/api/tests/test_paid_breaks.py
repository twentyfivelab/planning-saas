"""Pauses payées (20/11/2026) : réglage par site, figé sur chaque pause à sa création. Planning, compteurs du collaborateur et exports
distinguent les heures payées (travail effectif + pauses payées) du travail effectif (base du plafond mensuel et des règles), avec les
mêmes valeurs partout. Un changement ultérieur du réglage ne modifie jamais les heures déjà enregistrées. Données fictives."""
import csv
import io
import uuid

import pytest

from tests.conftest import make_client, register


@pytest.fixture
def t():
    o = make_client()
    register(o, "Pauses SA", f"pauses-{uuid.uuid4().hex[:8]}@example.com")
    sites = {}
    for code, name in (("PAYE", "Site payé"), ("NONP", "Site non payé")):
        r = o.post("/catalog/sites", json={"code": code, "name": name})
        assert r.status_code == 201, r.text
    sites = {x["code"]: x for x in o.get("/sites").json()}
    assert o.put(f"/sites/{sites['PAYE']['id']}", json={"code": "PAYE", "name": "Site payé", "paid_breaks": True}).status_code == 200
    assert o.post("/catalog/brands", json={"name": "Alpha"}).status_code == 201
    for site in ("PAYE", "NONP"):
        assert o.post("/catalog/animations", json={"site_code": site, "brand_code": "Alpha", "start": "09:00", "end": "18:00", "weekdays": [0, 1, 2, 3, 4],
                                                   "headcount": 1, "from_month": "2026-12"}).status_code == 201
    emps = [o.post("/employees", json={"code": c, "name": c.capitalize(), "brands": {"Alpha": "priority"}}).json() for c in ("ana", "ben", "cleo")]
    pid = o.post("/periods/ensure", json={"year": 2026, "month": 12}).json()["id"]
    r = o.post(f"/periods/{pid}/runs", json={"time_limit_s": 8}, headers={"Idempotency-Key": uuid.uuid4().hex})
    assert r.status_code == 202 and o.get(f"/runs/{r.json()['run_id']}").json()["status"] == "termine"
    return dict(o=o, pid=pid, emps=emps, sites=sites)


def test_heures_payees_planning_compteurs_exports(t):
    o, pid = t["o"], t["pid"]
    rows = o.get(f"/periods/{pid}/schedule").json()["assignments"]
    assert rows and all(a["break_minutes"] > 0 for a in rows)
    for a in rows:
        assert a["break_paid"] is (a["site"] == "PAYE")
        assert a["paid_minutes"] == a["effective_minutes"] + (a["break_minutes"] if a["site"] == "PAYE" else 0)
    # compteurs du collaborateur : mêmes valeurs que le planning
    for e in t["emps"]:
        mine = [a for a in rows if a["employee_id"] == e["id"]]
        tot = o.get(f"/employees/{e['id']}/month", params={"month": "2026-12"}).json()["totals"]
        assert tot["effective_minutes"] == sum(a["effective_minutes"] for a in mine)
        assert tot["paid_minutes"] == sum(a["paid_minutes"] for a in mine)
        assert tot["paid_break_minutes"] == sum(a["break_minutes"] for a in mine if a["break_paid"])
    # export CSV : colonnes « Pause payée » et « Payé (h) », mêmes valeurs
    r = o.get(f"/periods/{pid}/export.csv")
    assert r.status_code == 200
    lines = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig"))))
    head = lines[0]
    assert "Pause payée" in head and "Payé (h)" in head and "Effectif (h)" in head
    i_paid, i_eff, i_flag = head.index("Payé (h)"), head.index("Effectif (h)"), head.index("Pause payée")
    assert round(sum(float(x[i_paid]) for x in lines[1:]) * 60) == sum(a["paid_minutes"] for a in rows)
    assert round(sum(float(x[i_eff]) for x in lines[1:]) * 60) == sum(a["effective_minutes"] for a in rows)
    assert {x[i_flag] for x in lines[1:]} == {"oui", "non"}
    # Excel : récapitulatif par collaborateur avec les heures payées
    x = o.get(f"/periods/{pid}/export.xlsx")
    assert x.status_code == 200
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(x.content))
    recap = [r_ for r_ in wb.worksheets[1].iter_rows(values_only=True)]
    assert recap[0][:5] == ("Collaborateur", "Jours", "Heures effectives", "Pauses payées (h)", "Heures payées")
    assert round(sum(r_[4] for r_ in recap[1:]) * 60) == sum(a["paid_minutes"] for a in rows)


def test_changement_du_reglage_sans_effet_sur_les_heures_enregistrees(t):
    o, pid, s = t["o"], t["pid"], t["sites"]["PAYE"]
    before = {a["assignment_id"]: a["paid_minutes"] for a in o.get(f"/periods/{pid}/schedule").json()["assignments"]}
    assert o.put(f"/sites/{s['id']}", json={"code": "PAYE", "name": "Site payé", "paid_breaks": False}).status_code == 200
    after = {a["assignment_id"]: a["paid_minutes"] for a in o.get(f"/periods/{pid}/schedule").json()["assignments"]}
    assert after == before  # le passé ne change pas ; seuls les shifts attribués ensuite suivent le nouveau réglage
    site = next(x for x in o.get("/sites").json() if x["code"] == "PAYE")
    assert site["paid_breaks"] is False and site["continuous_presence"] is False  # mise à jour partielle : aucun autre champ remis à zéro
