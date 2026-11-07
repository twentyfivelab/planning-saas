"""préparation mensuelle : effectif, marques et sites actifs par mois, statut/brouillon des plannings, besoins datés, exceptions mensuelles"""
import os

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"

COLUMNS = [
    "ALTER TABLE planning_periods ADD COLUMN IF NOT EXISTS archived_at timestamptz",
    "ALTER TABLE planning_periods ADD COLUMN IF NOT EXISTS wizard_step integer",
    "ALTER TABLE sites ADD COLUMN IF NOT EXISTS archived_from date",
    "ALTER TABLE brands ADD COLUMN IF NOT EXISTS archived_from date",
    "ALTER TABLE staffing_requirements ADD COLUMN IF NOT EXISTS headcount integer NOT NULL DEFAULT 1",
    "ALTER TABLE staffing_requirements ADD COLUMN IF NOT EXISTS valid_from date",
    "ALTER TABLE staffing_requirements ADD COLUMN IF NOT EXISTS valid_to date",
    "ALTER TABLE employee_month_params ADD COLUMN IF NOT EXISTS max_days_set boolean NOT NULL DEFAULT false",
    "ALTER TABLE employee_month_params ADD COLUMN IF NOT EXISTS max_days_count integer",
    "ALTER TABLE employee_month_params ADD COLUMN IF NOT EXISTS max_days_period varchar(8)",
]
CHECKS = {
    "ck_req_headcount": "ALTER TABLE staffing_requirements ADD CONSTRAINT ck_req_headcount CHECK (headcount >= 1 AND headcount <= 50)",
    "ck_month_max_days": "ALTER TABLE employee_month_params ADD CONSTRAINT ck_month_max_days CHECK ((max_days_count IS NULL AND max_days_period IS NULL) OR "
                         "(max_days_count >= 1 AND ((max_days_period = 'week' AND max_days_count <= 7) OR (max_days_period = 'month' AND max_days_count <= 31))))",
}
TABLES = ["period_employees", "period_brands", "period_sites"]


def upgrade():
    import sys
    from pathlib import Path
    sys.path[:0] = [str(Path(__file__).resolve().parents[2])]
    from app.models import Base

    bind = op.get_bind()
    for stmt in COLUMNS:
        bind.execute(sa.text(stmt))
    for name, stmt in CHECKS.items():
        if not bind.execute(sa.text("select 1 from pg_constraint where conname=:n"), {"n": name}).scalar():
            bind.execute(sa.text(stmt))
    app_user = os.environ.get("APP_DB_USER", "planning_app")
    for t in TABLES:
        Base.metadata.tables[t].create(bind, checkfirst=True)
        bind.execute(sa.text(f'GRANT SELECT, INSERT, UPDATE, DELETE ON {t} TO "{app_user}"'))
        if not bind.execute(sa.text("select 1 from pg_policies where tablename=:t"), {"t": t}).scalar():
            bind.execute(sa.text(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY"))
            bind.execute(sa.text(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY"))
            bind.execute(sa.text(f"CREATE POLICY tenant_isolation ON {t} USING (tenant_id::text = current_setting('app.tenant_id', true)) "
                                 "WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))"))


def downgrade():
    raise RuntimeError("Pas de downgrade : restaurer depuis une sauvegarde (voir docs/backup-restore.md)")
