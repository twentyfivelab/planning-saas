"""plateforme WFM : clients, contrats commerciaux, missions, qualifications, relations, coûts, heures réelles, notifications, versions et rôles"""
import os

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"

COLUMNS = [
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS scope jsonb NOT NULL DEFAULT '{}'",
    "ALTER TABLE brands ADD COLUMN IF NOT EXISTS client_id uuid REFERENCES clients(id) ON DELETE SET NULL",
    "ALTER TABLE brands ADD COLUMN IF NOT EXISTS billing_rate_cents integer",
    "ALTER TABLE skills ADD COLUMN IF NOT EXISTS category varchar(16) NOT NULL DEFAULT 'competence'",
    "ALTER TABLE employee_skills ADD COLUMN IF NOT EXISTS valid_until date",
    "ALTER TABLE employment_contracts ADD COLUMN IF NOT EXISTS contract_type varchar(32)",
    "ALTER TABLE employment_contracts ADD COLUMN IF NOT EXISTS hourly_cost_cents integer",
    "ALTER TABLE employment_contracts ADD COLUMN IF NOT EXISTS legal_regime varchar(64)",
    "ALTER TABLE staffing_requirements ADD COLUMN IF NOT EXISTS mission_id uuid REFERENCES missions(id) ON DELETE CASCADE",
    "ALTER TABLE staffing_requirements ADD COLUMN IF NOT EXISTS priority integer NOT NULL DEFAULT 3",
    "ALTER TABLE relationship_preferences ADD COLUMN IF NOT EXISTS strict boolean NOT NULL DEFAULT false",
    "ALTER TABLE constraint_definitions ADD COLUMN IF NOT EXISTS source_url varchar(300)",
    "ALTER TABLE constraint_definitions ADD COLUMN IF NOT EXISTS reviewed_by uuid",
    "ALTER TABLE constraint_definitions ADD COLUMN IF NOT EXISTS reviewed_at timestamptz",
    "ALTER TABLE optimization_runs ADD COLUMN IF NOT EXISTS simulation boolean NOT NULL DEFAULT false",
    "ALTER TABLE optimization_runs ADD COLUMN IF NOT EXISTS applied_at timestamptz",
    "ALTER TABLE schedule_versions ADD COLUMN IF NOT EXISTS state varchar(16) NOT NULL DEFAULT 'snapshot'",
    "ALTER TABLE schedule_versions ADD COLUMN IF NOT EXISTS kind varchar(16) NOT NULL DEFAULT 'manual'",
    "ALTER TABLE schedule_versions ADD COLUMN IF NOT EXISTS run_id uuid",
    "ALTER TABLE schedule_versions ADD COLUMN IF NOT EXISTS validated_by uuid",
    "ALTER TABLE schedule_versions ADD COLUMN IF NOT EXISTS validated_at timestamptz",
    "ALTER TABLE schedule_versions ADD COLUMN IF NOT EXISTS published_by uuid",
    "ALTER TABLE schedule_versions ADD COLUMN IF NOT EXISTS note varchar(300)",
    # versions déjà publiées : leur état est repris tel quel
    "UPDATE schedule_versions SET state = 'published' WHERE published AND state = 'snapshot'",
]
CHECKS = {
    "ck_req_priority": "ALTER TABLE staffing_requirements ADD CONSTRAINT ck_req_priority CHECK (priority BETWEEN 1 AND 5)",
    "ck_contract_cost": "ALTER TABLE employment_contracts ADD CONSTRAINT ck_contract_cost CHECK (hourly_cost_cents IS NULL OR hourly_cost_cents >= 0)",
    "ck_brand_rate": "ALTER TABLE brands ADD CONSTRAINT ck_brand_rate CHECK (billing_rate_cents IS NULL OR billing_rate_cents >= 0)",
    "ck_version_state": "ALTER TABLE schedule_versions ADD CONSTRAINT ck_version_state CHECK (state IN ('snapshot','in_review','validated','published','superseded'))",
}
TABLES = ["clients", "client_contracts", "missions", "time_entries", "notifications"]


def upgrade():
    import sys
    from pathlib import Path
    sys.path[:0] = [str(Path(__file__).resolve().parents[2])]
    from app.models import Base
    from app.rbac import PERMISSIONS, ROLES

    bind = op.get_bind()
    app_user = os.environ.get("APP_DB_USER", "planning_app")
    for t in TABLES:  # tables d'abord : les colonnes ci-dessous y font référence
        Base.metadata.tables[t].create(bind, checkfirst=True)
        bind.execute(sa.text(f'GRANT SELECT, INSERT, UPDATE, DELETE ON {t} TO "{app_user}"'))
        if not bind.execute(sa.text("select 1 from pg_policies where tablename=:t"), {"t": t}).scalar():
            bind.execute(sa.text(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY"))
            bind.execute(sa.text(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY"))
            bind.execute(sa.text(f"CREATE POLICY tenant_isolation ON {t} USING (tenant_id::text = current_setting('app.tenant_id', true)) "
                                 "WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))"))
    for stmt in COLUMNS:
        bind.execute(sa.text(stmt))
    for name, stmt in CHECKS.items():
        if not bind.execute(sa.text("select 1 from pg_constraint where conname=:n"), {"n": name}).scalar():
            bind.execute(sa.text(stmt))
    # une compétence ne peut être attribuée qu'une fois au même collaborateur : doublons éventuels retirés avant la contrainte
    bind.execute(sa.text("DELETE FROM employee_skills a USING employee_skills b WHERE a.employee_id = b.employee_id AND a.skill_id = b.skill_id AND a.ctid > b.ctid"))
    if not bind.execute(sa.text("select 1 from pg_constraint where conname='employee_skills_employee_id_skill_id_key'")).scalar():
        bind.execute(sa.text("ALTER TABLE employee_skills ADD CONSTRAINT employee_skills_employee_id_skill_id_key UNIQUE (employee_id, skill_id)"))
    # rôles et permissions : source unique rbac.py
    for code in PERMISSIONS:
        bind.execute(sa.text("INSERT INTO permissions(code) VALUES (:c) ON CONFLICT DO NOTHING"), {"c": code})
    for code, (label, perms) in ROLES.items():
        bind.execute(sa.text("INSERT INTO roles(code, label) VALUES (:c, :l) ON CONFLICT (code) DO UPDATE SET label = :l"), {"c": code, "l": label})
        bind.execute(sa.text("DELETE FROM role_permissions WHERE role = :r"), {"r": code})
        for perm in perms:
            bind.execute(sa.text("INSERT INTO role_permissions(role, permission) VALUES (:r, :p)"), {"r": code, "p": perm})


def downgrade():
    raise RuntimeError("Pas de downgrade : restaurer depuis une sauvegarde (voir docs/backup-restore.md)")
