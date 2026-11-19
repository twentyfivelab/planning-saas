"""budget de base par marque, prérempli dans le budget de chaque nouveau mois (une seule fois par marque et par planning)"""
import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"


def upgrade():
    bind = op.get_bind()
    bind.execute(sa.text("ALTER TABLE brands ADD COLUMN IF NOT EXISTS base_budget_minutes integer"))
    bind.execute(sa.text("ALTER TABLE planning_periods ADD COLUMN IF NOT EXISTS budget_init jsonb"))
    # plannings déjà générés ou calculés : jamais de préremplissage rétroactif (leurs budgets restent exactement tels quels).
    # Les brouillons restent préremplissables, uniquement pour les marques qui n'ont pas encore de budget ce mois-là.
    bind.execute(sa.text("""UPDATE planning_periods p SET budget_init = '{"legacy": true}'::jsonb
        WHERE p.budget_init IS NULL AND p.deleted_at IS NULL AND (EXISTS (SELECT 1 FROM assignments a WHERE a.period_id = p.id)
              OR EXISTS (SELECT 1 FROM optimization_runs r WHERE r.period_id = p.id))"""))


def downgrade():
    raise RuntimeError("Pas de downgrade : restaurer depuis une sauvegarde (voir docs/backup-restore.md)")
