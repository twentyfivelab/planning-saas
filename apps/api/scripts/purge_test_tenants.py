"""Tenants laissés par les anciennes exécutions des tests API dans la base de l'application (avant la base de test isolée).

Par défaut : LISTE seulement (aucune modification). `--apply` supprime, dans UNE transaction, les seuls tenants identifiés AVEC CERTITUDE
comme créés par les tests. Il faut l'une des deux signatures exactes du code des tests, et rien d'autre :
  1. inscription par un test : nom de tenant utilisé par les tests ET toutes les adresses au format généré
     (`<préfixe>-<8 hexadécimaux>@example.com` ou `<32 hexadécimaux>@example.com`) ;
  2. démo rejouée par un test : nom « Démo Retail Genève » ET toutes les adresses sur un domaine aléatoire `<6 à 8 hexadécimaux>.example`.
Tout autre tenant est CONSERVÉ (doute), de même que les domaines protégés. Avant suppression : aucune référence depuis un tenant conservé.

    MIGRATION_DATABASE_URL=… python scripts/purge_test_tenants.py            # liste
    MIGRATION_DATABASE_URL=… python scripts/purge_test_tenants.py --apply    # supprime (après sauvegarde vérifiée)
"""
import os
import re
import sys

from sqlalchemy import create_engine, text

PROTECTED = {"rules.example", "e2e.example", "demo.example", "stack.example"}
TEST_NAMES = {"WFM SA", "Verif SA", "Tenant A", "Tenant B", "Rel SA", "RGPD SA", "Opp SA", "Légal SA", "Equipe SA", "Autre tenant", "Autre SA"}
REGISTERED = re.compile(r"^([a-z_]+-[0-9a-f]{8}|[0-9a-f]{32})@example\.com$")
SEEDED = re.compile(r"^(owner|manager|planner|auditor|collaborateur|[a-z_]+-[0-9a-f]{8})@([0-9a-f]{6,8})\.example$")


def classify(conn):
    rows = conn.execute(text("SELECT t.id, t.name, array_agg(u.email) FROM tenants t LEFT JOIN users u ON u.tenant_id = t.id GROUP BY t.id, t.name")).all()
    sure, doubt = [], []
    for tid, name, emails in rows:
        emails = [e for e in emails if e]
        domains = {e.split("@", 1)[1] for e in emails}
        if not emails or domains & PROTECTED:
            doubt.append((tid, name, emails[:1]))
            continue
        if name in TEST_NAMES and all(REGISTERED.match(e) for e in emails):
            sure.append((tid, name, sorted(emails)[0]))
        elif name == "Démo Retail Genève" and len(domains) == 1 and all(SEEDED.match(e) for e in emails):
            sure.append((tid, name, sorted(emails)[0]))
        else:
            doubt.append((tid, name, sorted(emails)[:1]))
    return sure, doubt


def cross_references(conn, ids) -> int:
    """Lignes d'un tenant CONSERVÉ qui désigneraient un collaborateur, une période ou un utilisateur d'un tenant supprimé."""
    q = """SELECT
      (SELECT count(*) FROM assignments a JOIN employees e ON e.id = a.employee_id WHERE e.tenant_id = ANY(:ids) AND NOT a.tenant_id = ANY(:ids))
    + (SELECT count(*) FROM shifts s JOIN planning_periods p ON p.id = s.period_id WHERE p.tenant_id = ANY(:ids) AND NOT s.tenant_id = ANY(:ids))
    + (SELECT count(*) FROM users u JOIN employees e ON e.id = u.employee_id WHERE e.tenant_id = ANY(:ids) AND NOT u.tenant_id = ANY(:ids))"""
    return conn.execute(text(q), {"ids": ids}).scalar()


def main():
    eng = create_engine(os.environ["MIGRATION_DATABASE_URL"])
    with eng.begin() as conn:
        sure, doubt = classify(conn)
        print(f"{len(sure)} tenant(s) de test identifiés avec certitude ; {len(doubt)} conservé(s)")
        by_name: dict = {}
        for _t, n, _e in sure:
            by_name[n] = by_name.get(n, 0) + 1
        print("  supprimables par nom :", dict(sorted(by_name.items())))
        for tid, name, em in doubt:
            print(f"  conservé : {name} {em} {tid}")
        ids = [t[0] for t in sure]
        refs = cross_references(conn, ids) if ids else 0
        print(f"  références depuis un tenant conservé : {refs}")
        if "--apply" not in sys.argv:
            print("Aucune modification (ajoutez --apply pour supprimer).")
            return
        if refs:
            sys.exit("Références croisées détectées : suppression refusée.")
        conn.execute(text("DELETE FROM sessions WHERE tenant_id = ANY(:ids)"), {"ids": ids})
        n = conn.execute(text("DELETE FROM tenants WHERE id = ANY(:ids)"), {"ids": ids}).rowcount
        print(f"{n} tenant(s) supprimé(s), données rattachées comprises (suppression en cascade).")


if __name__ == "__main__":
    main()
