"""rappels « À régulariser » : doubles affectations confirmées provisoirement"""
import os

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"


def upgrade():
    import sys
    from pathlib import Path
    sys.path[:0] = [str(Path(__file__).resolve().parents[2])]
    from app.models import Base

    bind = op.get_bind()
    app_user = os.environ.get("APP_DB_USER", "planning_app")
    Base.metadata.tables["regularizations"].create(bind, checkfirst=True)
    bind.execute(sa.text(f'GRANT SELECT, INSERT, UPDATE, DELETE ON regularizations TO "{app_user}"'))
    if not bind.execute(sa.text("select 1 from pg_policies where tablename='regularizations'")).scalar():
        bind.execute(sa.text("ALTER TABLE regularizations ENABLE ROW LEVEL SECURITY"))
        bind.execute(sa.text("ALTER TABLE regularizations FORCE ROW LEVEL SECURITY"))
        bind.execute(sa.text("CREATE POLICY tenant_isolation ON regularizations USING (tenant_id::text = current_setting('app.tenant_id', true)) "
                             "WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))"))


def downgrade():
    raise RuntimeError("Pas de downgrade : restaurer depuis une sauvegarde (voir docs/backup-restore.md)")
