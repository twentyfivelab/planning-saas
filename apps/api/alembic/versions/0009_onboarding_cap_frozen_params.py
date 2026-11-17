"""fiche d'ajout et suppression des collaborateurs, jours minimum / maximum par mois, plafond mensuel d'heures de l'entreprise,
paramètres conservés par chaque planning, suivi du calcul"""
import os
import re

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"

COLUMNS = [
    "ALTER TABLE employees ADD COLUMN IF NOT EXISTS first_name varchar(100)",
    "ALTER TABLE employees ADD COLUMN IF NOT EXISTS last_name varchar(100)",
    "ALTER TABLE employees ADD COLUMN IF NOT EXISTS birth_date date",
    "ALTER TABLE employees ADD COLUMN IF NOT EXISTS address_street varchar(200)",
    "ALTER TABLE employees ADD COLUMN IF NOT EXISTS address_postal_code varchar(16)",
    "ALTER TABLE employees ADD COLUMN IF NOT EXISTS address_city varchar(100)",
    "ALTER TABLE employees ADD COLUMN IF NOT EXISTS address_country varchar(100)",
    "ALTER TABLE employees ADD COLUMN IF NOT EXISTS phone varchar(32)",
    "ALTER TABLE employees ADD COLUMN IF NOT EXISTS email varchar(200)",
    "ALTER TABLE employees ADD COLUMN IF NOT EXISTS min_days_month integer",
    "ALTER TABLE employees ADD COLUMN IF NOT EXISTS max_days_month integer",
    "ALTER TABLE employees ADD COLUMN IF NOT EXISTS deleted_at timestamptz",
    "ALTER TABLE employees ADD COLUMN IF NOT EXISTS removed_on date",
    "ALTER TABLE employees ADD COLUMN IF NOT EXISTS deleted_by uuid",
    "ALTER TABLE employee_month_params ADD COLUMN IF NOT EXISTS days_set boolean NOT NULL DEFAULT false",
    "ALTER TABLE employee_month_params ADD COLUMN IF NOT EXISTS min_days integer",
    "ALTER TABLE employee_month_params ADD COLUMN IF NOT EXISTS max_days integer",
    # règle interne de l'entreprise demandée : 176 h de travail effectif par collaborateur et par mois (modifiable par tenant)
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS monthly_hours_cap_minutes integer DEFAULT 10560",
    "ALTER TABLE planning_periods ADD COLUMN IF NOT EXISTS frozen_params jsonb",
    "ALTER TABLE planning_periods ADD COLUMN IF NOT EXISTS frozen_at timestamptz",
    "ALTER TABLE planning_periods ADD COLUMN IF NOT EXISTS frozen_source varchar(16)",
    "ALTER TABLE optimization_runs ADD COLUMN IF NOT EXISTS progress jsonb",
]
CHECKS = {
    "ck_emp_min_days_month": "ALTER TABLE employees ADD CONSTRAINT ck_emp_min_days_month CHECK (min_days_month IS NULL OR (min_days_month BETWEEN 1 AND 31))",
    "ck_emp_max_days_month": "ALTER TABLE employees ADD CONSTRAINT ck_emp_max_days_month CHECK (max_days_month IS NULL OR (max_days_month BETWEEN 1 AND 31))",
    "ck_emp_days_order": "ALTER TABLE employees ADD CONSTRAINT ck_emp_days_order CHECK (min_days_month IS NULL OR max_days_month IS NULL OR min_days_month <= max_days_month)",
    "ck_month_days_order": "ALTER TABLE employee_month_params ADD CONSTRAINT ck_month_days_order CHECK (min_days IS NULL OR max_days IS NULL OR min_days <= max_days)",
    "ck_tenant_monthly_cap": "ALTER TABLE tenants ADD CONSTRAINT ck_tenant_monthly_cap CHECK (monthly_hours_cap_minutes IS NULL OR monthly_hours_cap_minutes > 0)",
}
UPPER = re.compile(r"^[^a-zà-ÿ]*[A-ZÀ-Þ][^a-zà-ÿ]*$")


def split_name(name: str):
    """« Prénom NOM » : le nom de famille est la suite finale de mots en MAJUSCULES ; sans majuscules, le nom reste non renseigné
    (jamais deviné). « Léa » -> (Léa, None) ; « Jean-Marc DE LA ROCHE » -> (Jean-Marc, DE LA ROCHE) (exemples fictifs)."""
    parts = (name or "").split()
    k = len(parts)
    while k > 1 and UPPER.match(parts[k - 1]):
        k -= 1
    first, last = " ".join(parts[:k]), " ".join(parts[k:])
    return (first or None), (last or None)


def upgrade():
    import sys
    from pathlib import Path
    sys.path[:0] = [str(Path(__file__).resolve().parents[2])]

    bind = op.get_bind()
    for stmt in COLUMNS:
        bind.execute(sa.text(stmt))
    for name, stmt in CHECKS.items():
        if not bind.execute(sa.text("select 1 from pg_constraint where conname=:n"), {"n": name}).scalar():
            bind.execute(sa.text(stmt))
    # identité : prénom et nom séparés à partir du nom affiché (sans rien inventer)
    for eid, name in bind.execute(sa.text("SELECT id, name FROM employees WHERE first_name IS NULL AND last_name IS NULL")).all():
        first, last = split_name(name)
        bind.execute(sa.text("UPDATE employees SET first_name = :f, last_name = :l WHERE id = :i"), {"f": first, "l": last, "i": eid})
    # « N jours maximum sur le mois » : repris dans le nouveau champ « maximum de jours par mois » (même sens), fiche et exceptions du mois
    bind.execute(sa.text("UPDATE employees SET max_days_month = max_days_count, max_days_count = NULL, max_days_period = NULL "
                         "WHERE max_days_period = 'month' AND max_days_count BETWEEN 1 AND 31"))
    bind.execute(sa.text("UPDATE employee_month_params SET days_set = true, min_days = NULL, max_days = max_days_count, max_days_set = false, "
                         "max_days_count = NULL, max_days_period = NULL WHERE max_days_set AND max_days_period = 'month'"))

    # Plannings existants : ils conservent désormais les paramètres en vigueur AU MOMENT DE CETTE MISE EN PLACE (ceux de leur création
    # n'ont pas été enregistrés à l'époque). Établis avant le plafond mensuel, ils ne reçoivent pas ce plafond : rien n'y change.
    periods = bind.execute(sa.text("SELECT DISTINCT p.id, p.tenant_id FROM planning_periods p JOIN assignments a ON a.period_id = p.id "
                                   "WHERE p.frozen_params IS NULL")).all()
    if not periods:
        return
    from sqlalchemy.orm import Session
    from app import models as m
    from app.frozen import snapshot
    from app.services_bridge import build_input
    import json
    from datetime import datetime, timezone

    app_role = os.environ.get("APP_DB_USER", "planning_app")
    bind.execute(sa.text(f'SET LOCAL ROLE "{app_role}"'))  # lecture sous RLS, tenant par tenant (aucun mélange de données)
    now = datetime.now(timezone.utc)
    for pid, tid in periods:
        bind.execute(sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tid)})
        db = Session(bind=bind)
        try:
            p = db.get(m.PlanningPeriod, pid)
            cap: dict = {}
            build_input(db, p, {"params": "current"}, capture=cap)
            cfg = dict(cap["config"])
            cfg["monthly_cap_minutes"] = None
            snap = snapshot(cap["employees"], cfg, "mise_en_place")
        finally:
            db.close()
        bind.execute(sa.text("UPDATE planning_periods SET frozen_params = CAST(:s AS jsonb), frozen_at = :t, frozen_source = 'mise_en_place' WHERE id = :i"),
                     {"s": json.dumps(snap), "t": now, "i": pid})
    bind.execute(sa.text("RESET ROLE"))


def downgrade():
    raise RuntimeError("Pas de downgrade : restaurer depuis une sauvegarde (voir docs/backup-restore.md)")
