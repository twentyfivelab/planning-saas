"""paramètres mensuels (quota de dimanches par mois), un seul titulaire par shift"""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"


def upgrade():
    import os
    import sys
    from pathlib import Path
    sys.path[:0] = [str(Path(__file__).resolve().parents[2])]
    from app.models import Base

    bind = op.get_bind()
    Base.metadata.tables["employee_month_params"].create(bind, checkfirst=True)
    app_user = os.environ.get("APP_DB_USER", "planning_app")
    bind.execute(sa.text(f'GRANT SELECT, INSERT, UPDATE, DELETE ON employee_month_params TO "{app_user}"'))
    if not bind.execute(sa.text("select 1 from pg_policies where tablename='employee_month_params'")).scalar():
        bind.execute(sa.text("ALTER TABLE employee_month_params ENABLE ROW LEVEL SECURITY"))
        bind.execute(sa.text("ALTER TABLE employee_month_params FORCE ROW LEVEL SECURITY"))
        bind.execute(sa.text(
            "CREATE POLICY tenant_isolation ON employee_month_params USING (tenant_id::text = current_setting('app.tenant_id', true)) "
            "WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))"))
    # Les quotas historiques de la fiche restent la valeur par défaut tant qu'aucune valeur n'est saisie pour un mois ; ils sont
    # reportés mois par mois par l'application (sous contexte tenant, RLS) lors de la première saisie mensuelle d'un collaborateur.
    dup = bind.execute(sa.text("select shift_id from assignments group by shift_id having count(*) > 1 limit 1")).scalar()
    if dup:
        raise RuntimeError(f"Migration interrompue : le shift {dup} a plusieurs titulaires. Corrigez les données puis relancez.")
    if not bind.execute(sa.text("select 1 from pg_constraint where conname='uq_assignment_shift'")).scalar():
        bind.execute(sa.text("ALTER TABLE assignments ADD CONSTRAINT uq_assignment_shift UNIQUE (shift_id)"))


def downgrade():
    raise RuntimeError("Pas de downgrade : restaurer depuis une sauvegarde (voir docs/backup-restore.md)")
