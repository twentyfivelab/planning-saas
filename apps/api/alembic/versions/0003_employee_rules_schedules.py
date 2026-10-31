"""fiche collaborateur (jours max, préférence horaire, quota de dimanches), horaires autorisés par portée, budgets stricts"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"

STATEMENTS = [
    "ALTER TABLE employees ADD COLUMN IF NOT EXISTS max_days_count integer",
    "ALTER TABLE employees ADD COLUMN IF NOT EXISTS max_days_period varchar(8)",
    "ALTER TABLE employees ADD COLUMN IF NOT EXISTS time_pref varchar(8)",
    "ALTER TABLE employees ADD COLUMN IF NOT EXISTS time_pref_strict boolean NOT NULL DEFAULT false",
    "ALTER TABLE employees ADD COLUMN IF NOT EXISTS sunday_quota integer",
    "ALTER TABLE employees ADD COLUMN IF NOT EXISTS sunday_mode varchar(8) NOT NULL DEFAULT 'max'",
    "ALTER TABLE shift_templates ADD COLUMN IF NOT EXISTS scope_type varchar(8)",
    "ALTER TABLE shift_templates ADD COLUMN IF NOT EXISTS scope_code varchar(64)",
    "ALTER TABLE monthly_budgets ADD COLUMN IF NOT EXISTS strict boolean NOT NULL DEFAULT true",
    # cohérence des paramètres, garantie aussi côté base
    "ALTER TABLE employees ADD CONSTRAINT ck_emp_max_days CHECK ((max_days_count IS NULL AND max_days_period IS NULL) OR "
    "(max_days_count >= 1 AND ((max_days_period = 'week' AND max_days_count <= 7) OR (max_days_period = 'month' AND max_days_count <= 31))))",
    "ALTER TABLE employees ADD CONSTRAINT ck_emp_time_pref CHECK (time_pref IS NULL OR time_pref IN ('matin','middle','soir'))",
    "ALTER TABLE employees ADD CONSTRAINT ck_emp_sunday CHECK ((sunday_quota IS NULL OR (sunday_quota >= 0 AND sunday_quota <= 5)) AND sunday_mode IN ('max','exact'))",
]


def upgrade():
    bind = op.get_bind()
    for stmt in STATEMENTS:
        if stmt.startswith("ALTER TABLE employees ADD CONSTRAINT"):
            name = stmt.split("ADD CONSTRAINT ")[1].split(" ")[0]
            if bind.execute(sa.text("select 1 from pg_constraint where conname=:n"), {"n": name}).scalar():
                continue
        bind.execute(sa.text(stmt))


def downgrade():
    raise RuntimeError("Pas de downgrade : restaurer depuis une sauvegarde (voir docs/backup-restore.md)")
