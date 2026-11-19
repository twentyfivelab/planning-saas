"""propositions de remplacement envoyées aux collaborateurs (une demande ouverte et une proposition en attente au plus par shift)"""
import os

import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"


def upgrade():
    import sys
    from pathlib import Path
    sys.path[:0] = [str(Path(__file__).resolve().parents[2])]
    from app.models import Base

    bind = op.get_bind()
    app_user = os.environ.get("APP_DB_USER", "planning_app")
    for name in ("replacement_requests", "replacement_offers"):
        Base.metadata.tables[name].create(bind, checkfirst=True)
        bind.execute(sa.text(f'GRANT SELECT, INSERT, UPDATE, DELETE ON {name} TO "{app_user}"'))
        if not bind.execute(sa.text("select 1 from pg_policies where tablename=:t"), {"t": name}).scalar():
            bind.execute(sa.text(f"ALTER TABLE {name} ENABLE ROW LEVEL SECURITY"))
            bind.execute(sa.text(f"ALTER TABLE {name} FORCE ROW LEVEL SECURITY"))
            bind.execute(sa.text(f"CREATE POLICY tenant_isolation ON {name} USING (tenant_id::text = current_setting('app.tenant_id', true)) "
                                 "WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))"))
    # garanties en base, indépendantes du code : une demande ouverte et une proposition en attente au plus par shift
    bind.execute(sa.text("CREATE UNIQUE INDEX IF NOT EXISTS uq_replacement_open_per_shift ON replacement_requests (shift_id) WHERE status = 'open'"))
    bind.execute(sa.text("CREATE UNIQUE INDEX IF NOT EXISTS uq_replacement_pending_per_shift ON replacement_offers (shift_id) WHERE status = 'pending'"))


def downgrade():
    raise RuntimeError("Pas de downgrade : restaurer depuis une sauvegarde (voir docs/backup-restore.md)")
