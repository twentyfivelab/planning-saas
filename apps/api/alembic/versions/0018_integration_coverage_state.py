"""dernier état de couverture d'une marque intégrée manuellement (notifications envoyées seulement aux changements d'état)"""
import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"


def upgrade():
    bind = op.get_bind()
    for col, typ in (("last_state", "varchar(16)"), ("last_remaining", "integer"), ("last_remaining_minutes", "integer"), ("state_at", "timestamptz")):
        bind.execute(sa.text(f"ALTER TABLE period_integrations ADD COLUMN IF NOT EXISTS {col} {typ}"))


def downgrade():
    raise RuntimeError("Pas de downgrade : restaurer depuis une sauvegarde (voir docs/backup-restore.md)")
