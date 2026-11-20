"""Entreprise de DÉMONSTRATION entièrement fictive (noms, marques, sites, horaires) pour présenter la plateforme sans aucune donnée réelle.

    .venv/bin/python scripts/ops/demo_seed.py [--api http://localhost:8000]

Construite uniquement par l'API publique (mêmes contrôles qu'un vrai client) dans une NOUVELLE entreprise : aucune autre entreprise, aucun
planning existant n'est lu ni modifié. Idempotent : si l'entreprise existe déjà, le script s'arrête et rappelle où trouver les accès.
Mot de passe : généré, enregistré uniquement dans demo/acces-demonstration.local.txt (fichier ignoré par Git, droits 600).

Contenu (tout est fictif) :
- 3 sites (dont un aéroport à présence continue et pauses payées), 5 marques, besoins obligatoires et optionnels, budgets du mois ;
- 25 collaborateurs : temps partiels avec objectif contractuel, indisponibilités, maximum de jours, un profil uniquement en renfort, une
  nouvelle recrue accompagnée par sa tutrice PENDANT TOUTE LA PLAGE de ses shifts, un binôme ;
- comptes : propriétaire, manager, planificateur, responsable de marque, auditeur, deux collaborateurs (« Mon espace ») ;
- novembre 2026 généré puis validé et publié ; décembre 2026 généré (brouillon) ; une proposition de remplacement en attente ;
- janvier 2027 n'est PAS créé : il sert à montrer l'assistant de création en direct."""
import argparse
import os
import secrets
import sys
import time
import uuid

import httpx

DOMAIN = os.environ.get("DEMO_DOMAIN", "horizon-demo.example")
TENANT = "Horizon Retail SA (démonstration)"
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CRED = os.environ.get("DEMO_CRED", os.path.join(ROOT, "demo", "acces-demonstration.local.txt"))

SITES = [("AERO", "Aéroport — Hall Est", True, True), ("GARE", "Gare Centrale", False, False), ("LUM", "Centre Lumière", False, False)]
BRANDS = ["Aurelia Cosmétiques", "Nordique Café", "Solstice Parfums", "Atelier Verre", "Kiosque Mobile"]
# (site, marque, début, fin, jours, effectif, obligatoire)
NEEDS = [("AERO", "Aurelia Cosmétiques", "07:00", "16:00", [0, 1, 2, 3, 4, 5, 6], 2, True),  # 2 personnes : accompagnement possible
         ("AERO", "Aurelia Cosmétiques", "12:00", "21:00", [0, 1, 2, 3, 4, 5, 6], 1, True),
         ("AERO", "Nordique Café", "06:00", "15:00", [0, 1, 2, 3, 4, 5, 6], 1, True),
         ("AERO", "Nordique Café", "14:00", "23:00", [0, 1, 2, 3, 4, 5, 6], 1, True),
         ("GARE", "Solstice Parfums", "09:00", "18:00", [0, 1, 2, 3, 4, 5], 2, True),
         ("GARE", "Atelier Verre", "10:00", "19:00", [3, 4, 5], 1, False),          # optionnel, avec budget
         ("LUM", "Aurelia Cosmétiques", "10:00", "19:00", [0, 1, 2, 3, 4, 5], 1, True),
         ("LUM", "Kiosque Mobile", "11:00", "18:00", [5, 6], 1, False)]               # optionnel, sans budget
P, S, R = "priority", "secondary", "reinforce"
A, N, SO, AV, K = BRANDS
# (code, nom, marques, options)
TEAM = [
    ("lmarchand", "Léa Marchand", {A: P, N: S}, {}),
    ("nkeller", "Noah Keller", {N: P, A: R}, {}),
    ("iduval", "Inès Duval", {A: P, SO: S}, {"contract": 120}),
    ("ymoreau", "Yanis Moreau", {N: P}, {"unavailable": [6]}),
    ("crossi", "Clara Rossi", {SO: P, AV: P}, {}),
    ("hlambert", "Hugo Lambert", {SO: P, A: S}, {"max_days_month": 16}),
    ("mfischer", "Maya Fischer", {A: P, K: P}, {}),
    ("equillet", "Elias Quillet", {N: P, K: S}, {"contract": 100}),
    ("zgirard", "Zoé Girard", {AV: P, SO: S}, {"unavailable": [0]}),
    ("lperret", "Liam Perret", {N: P, A: S}, {}),
    ("nbauer", "Nina Bauer", {A: P}, {"mentor": "lmarchand"}),                 # nouvelle recrue : tutrice présente toute la plage
    ("achevalier", "Adam Chevalier", {SO: P}, {}),
    ("sricci", "Sofia Ricci", {A: P, SO: R}, {}),
    ("tweber", "Tom Weber", {N: P, SO: R}, {"unavailable": [5]}),
    ("amorel", "Alice Morel", {SO: P, AV: S}, {"contract": 80}),
    ("rnavarro", "Rayan Navarro", {N: P, A: R}, {}),
    ("lfavre", "Lina Favre", {A: P, K: S}, {"pair": "mfischer"}),
    ("groux", "Gabriel Roux", {SO: P, N: R}, {}),
    ("eschmid", "Emma Schmid", {A: P, N: P}, {"max_days_month": 18}),
    ("ndubois", "Nathan Dubois", {N: P, SO: S}, {}),
    ("jhuber", "Jade Huber", {AV: P, K: P}, {}),
    ("lmercier", "Louis Mercier", {SO: P, A: S}, {}),
    ("cvidal", "Chloé Vidal", {A: P, SO: S}, {"unavailable": [2]}),
    ("sbrunner", "Samuel Brunner", {A: R, N: R, SO: R}, {}),                    # uniquement en renfort
    ("prey", "Paul Rey", {SO: P, AV: S}, {}),
]
BUDGETS_H = {A: 1150, N: 560, SO: 420, AV: 64}  # Kiosque Mobile : aucun budget (volume non visé)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default=os.environ.get("API_URL", "http://localhost:8000"))
    api = ap.parse_args().api
    c = httpx.Client(base_url=api, timeout=120)
    if os.path.exists(CRED):
        print(f"L'entreprise de démonstration existe déjà : accès dans {CRED}")
        return
    pw = secrets.token_urlsafe(14) + "-Aa1"
    r = c.post("/auth/register", json={"tenant_name": TENANT, "name": "Camille Arnaud (démo)", "email": f"proprietaire@{DOMAIN}", "password": pw})
    if r.status_code != 201:
        sys.exit(f"Création impossible ({r.status_code}) : {r.text[:300]}")
    c.headers["X-CSRF-Token"] = r.json()["csrf_token"]

    def call(method, path, **kw):
        x = c.request(method, path, **kw)
        if x.status_code >= 300:
            sys.exit(f"{method} {path} : {x.status_code} {x.text[:400]}")
        return x.json() if x.content else None

    for code, name, cont, paid in SITES:
        call("POST", "/catalog/sites", json={"code": code, "name": name})
    for s in call("GET", "/sites"):
        cont, paid = next((x[2], x[3]) for x in SITES if x[0] == s["code"])
        if cont or paid:
            call("PUT", f"/sites/{s['id']}", json={"code": s["code"], "name": s["name"], "continuous_presence": cont, "paid_breaks": paid})
    for b in BRANDS:
        call("POST", "/catalog/brands", json={"name": b})
    for site, brand, start, end, days, head, mand in NEEDS:
        call("POST", "/catalog/animations", json={"site_code": site, "brand_code": brand, "start": start, "end": end, "weekdays": days,
                                                  "headcount": head, "mandatory": mand, "from_month": "2026-11"})
    emp = {}
    for code, name, brands, opt in TEAM:
        body = {"code": code, "name": name, "brands": brands}
        if opt.get("max_days_month"):
            body["max_days_month"] = opt["max_days_month"]
        emp[code] = call("POST", "/employees", json=body)
        # un contrat pour chacun (sinon le planning reste une « simulation exploratoire », non publiable) : temps partiel avec objectif
        # mensuel explicite, ou temps plein sans objectif (cible commune d'heures)
        if opt.get("contract"):
            call("POST", "/contracts", json={"employee_id": emp[code]["id"], "contract_type": "temps partiel", "monthly_target_minutes": opt["contract"] * 60,
                                             "weekly_max_minutes": 32 * 60})
        else:
            call("POST", "/contracts", json={"employee_id": emp[code]["id"], "contract_type": "temps plein", "weekly_max_minutes": 42 * 60})
        for wd in opt.get("unavailable", []):
            call("POST", "/unavailabilities", json={"employee_id": emp[code]["id"], "weekday": wd, "reason": "indisponibilité hebdomadaire (fictive)"})
    for code, _n, _b, opt in TEAM:
        if opt.get("mentor"):
            call("POST", "/relationship-preferences", json={"employee_id": emp[code]["id"], "other_employee_id": emp[opt["mentor"]]["id"], "kind": "mentor",
                                                            "strict": True, "scope": "full", "note": "accompagnement pendant tout le shift"})
        if opt.get("pair"):
            call("POST", "/relationship-preferences", json={"employee_id": emp[code]["id"], "other_employee_id": emp[opt["pair"]]["id"], "kind": "work_together",
                                                            "strict": False, "scope": "overlap"})
    for month in ("2026-11-01", "2026-12-01"):
        for brand, hours in BUDGETS_H.items():
            call("POST", "/budgets", json={"brand_code": brand, "month": month, "target_minutes": hours * 60, "strict": brand != AV})
    users = [("manager", "Manon Ostendorf (démo)", "manager", None), ("planification", "Paul Girardin (démo)", "planner", None),
             ("marque", "Sarah Kunz (démo)", "brand_manager", None), ("audit", "Marc Steiner (démo)", "auditor", None),
             ("lea.marchand", "Léa Marchand", "employee", "lmarchand"), ("nina.bauer", "Nina Bauer", "employee", "nbauer")]
    for local, name, role, link in users:
        u = call("POST", "/users", json={"email": f"{local}@{DOMAIN}", "name": name, "role": role, "password": pw,
                                         **({"employee_id": emp[link]["id"]} if link else {})})
        if role == "brand_manager":  # périmètre : une seule marque
            call("PATCH", f"/users/{u['id']}", json={"scope_brands": [A]})

    def generate(year, month):
        pid = call("POST", "/periods/ensure", json={"year": year, "month": month})["id"]
        rid = call("POST", f"/periods/{pid}/runs", json={"time_limit_s": 30}, headers={"Idempotency-Key": uuid.uuid4().hex})["run_id"]
        for _ in range(240):
            run = call("GET", f"/runs/{rid}")
            if run["status"] not in ("en_attente", "en_cours"):
                break
            time.sleep(1)
        print(f"  {year}-{month:02d} : génération {run['status']}, {run.get('save', {}).get('outcome')}")
        return pid
    nov = generate(2026, 11)
    v = call("POST", f"/periods/{nov}/versions", json={})
    vid = v.get("id") or v.get("version_id")
    for step in ("submit", "validate", "publish"):
        x = c.post(f"/versions/{vid}/{step}", json={})
        print(f"  novembre : {step} -> {x.status_code}")
    dec = generate(2026, 12)
    # une proposition de remplacement en attente (Nina ne peut pas : tutrice exigée ; on propose un shift de Sofia à Léa si compatible)
    rows = call("GET", f"/periods/{dec}/schedule")["assignments"]
    for a in rows:
        rk = call("GET", f"/shifts/{a['shift_id']}/replacements")
        cand = next((x for x in rk["candidates"] if x.get("employee_uuid") == emp["lmarchand"]["id"] and x["status"] == "compatible"), None)
        if cand:
            x = c.post(f"/shifts/{a['shift_id']}/replacement-requests", json={"start_employee_id": cand["employee_uuid"], "response_minutes": 2880})
            print(f"  proposition de remplacement à Léa Marchand : {x.status_code}")
            break
    os.makedirs(os.path.dirname(CRED), exist_ok=True)
    with open(CRED, "w") as f:
        os.chmod(CRED, 0o600)
        f.write(f"Entreprise de démonstration (fictive) : {TENANT}\nAdresse : http://localhost:3000\nMot de passe (tous les comptes) : {pw}\n\nComptes :\n")
        for local, role in (("proprietaire", "propriétaire"), ("manager", "manager"), ("planification", "planificateur"),
                            ("marque", "responsable de marque"), ("audit", "auditeur"), ("lea.marchand", "collaboratrice (Mon espace)"),
                            ("nina.bauer", "collaboratrice, nouvelle recrue (Mon espace)")):
            f.write(f"  {local}@{DOMAIN} — {role}\n")
    print(f"Démonstration prête. Accès : {CRED}")


if __name__ == "__main__":
    main()
