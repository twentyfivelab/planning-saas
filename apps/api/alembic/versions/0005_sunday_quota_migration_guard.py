"""report des quotas de dimanches historiques : marqueur de report (la valeur historique n'est plus jamais effacée)"""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"


def upgrade():
    bind = op.get_bind()
    bind.execute(sa.text("ALTER TABLE employees ADD COLUMN IF NOT EXISTS sunday_quota_migrated_at timestamptz"))


def downgrade():
    raise RuntimeError("Pas de downgrade : restaurer depuis une sauvegarde (voir docs/backup-restore.md)")
