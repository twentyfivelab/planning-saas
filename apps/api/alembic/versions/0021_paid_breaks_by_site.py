"""pauses payées par site, index du journal d'audit pour l'empreinte de révision (20/11/2026) : certaines boutiques ou certains clients rémunèrent la pause. Le statut est fixé sur chaque pause à
sa création (un changement ultérieur du réglage ne modifie jamais les heures passées) ; les compteurs et exports distinguent les heures
payées (travail effectif + pauses payées) du travail effectif (base du plafond mensuel et des règles)."""
import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"


def upgrade():
    op.get_bind().execute(sa.text("ALTER TABLE sites ADD COLUMN IF NOT EXISTS paid_breaks boolean NOT NULL DEFAULT false"))
    # empreinte de révision (resynchronisation des écrans, cache des lectures d'affichage) : sans parcourir tout le journal d'audit
    op.get_bind().execute(sa.text("CREATE INDEX IF NOT EXISTS ix_audit_logs_tenant_created ON audit_logs (tenant_id, created_at)"))


def downgrade():
    raise RuntimeError("Pas de downgrade : restaurer depuis une sauvegarde (voir docs/backup-restore.md)")
