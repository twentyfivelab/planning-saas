"""demandes des collaborateurs (congé, absence, échange) avec circuit d'approbation"""
import os

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"


def upgrade():
    import sys
    from pathlib import Path
    sys.path[:0] = [str(Path(__file__).resolve().parents[2])]
    from app.models import Base

    bind = op.get_bind()
    app_user = os.environ.get("APP_DB_USER", "planning_app")
    name = "employee_requests"
    Base.metadata.tables[name].create(bind, checkfirst=True)
    bind.execute(sa.text(f'GRANT SELECT, INSERT, UPDATE, DELETE ON {name} TO "{app_user}"'))
    if not bind.execute(sa.text("select 1 from pg_policies where tablename=:t"), {"t": name}).scalar():
        bind.execute(sa.text(f"ALTER TABLE {name} ENABLE ROW LEVEL SECURITY"))
        bind.execute(sa.text(f"ALTER TABLE {name} FORCE ROW LEVEL SECURITY"))
        bind.execute(sa.text(f"CREATE POLICY tenant_isolation ON {name} USING (tenant_id::text = current_setting('app.tenant_id', true)) "
                             "WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))"))


def downgrade():
    raise RuntimeError("Pas de downgrade : restaurer depuis une sauvegarde (voir docs/backup-restore.md)")
