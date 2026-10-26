"""horaires supposés : marquage des modèles de shifts non validés"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"


def upgrade():
    bind = op.get_bind()
    bind.execute(sa.text("ALTER TABLE shift_templates ADD COLUMN IF NOT EXISTS is_hypothesis boolean NOT NULL DEFAULT false"))
    bind.execute(sa.text("ALTER TABLE shift_templates ADD COLUMN IF NOT EXISTS hypothesis_note varchar(300)"))


def downgrade():
    raise RuntimeError("Pas de downgrade : restaurer depuis une sauvegarde (voir docs/backup-restore.md)")
