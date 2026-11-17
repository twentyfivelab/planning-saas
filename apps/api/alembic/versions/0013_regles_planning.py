"""règles de planning : portée des relations, absences partielles, temps de déplacement entre sites, présence continue"""
import os

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"

NEW_TABLES = ("partial_absences", "site_travel")


def upgrade():
    import sys
    from pathlib import Path
    sys.path[:0] = [str(Path(__file__).resolve().parents[2])]
    from app.models import Base

    bind = op.get_bind()
    app_user = os.environ.get("APP_DB_USER", "planning_app")
    # colonnes ajoutées avec une valeur par défaut : les données existantes gardent exactement leur sens actuel
    bind.execute(sa.text("ALTER TABLE relationship_preferences ADD COLUMN IF NOT EXISTS scope varchar(16) NOT NULL DEFAULT 'site_day'"))
    bind.execute(sa.text("ALTER TABLE sites ADD COLUMN IF NOT EXISTS continuous_presence boolean NOT NULL DEFAULT false"))
    for name in NEW_TABLES:
        Base.metadata.tables[name].create(bind, checkfirst=True)
        bind.execute(sa.text(f'GRANT SELECT, INSERT, UPDATE, DELETE ON {name} TO "{app_user}"'))
        if not bind.execute(sa.text("select 1 from pg_policies where tablename=:t"), {"t": name}).scalar():
            bind.execute(sa.text(f"ALTER TABLE {name} ENABLE ROW LEVEL SECURITY"))
            bind.execute(sa.text(f"ALTER TABLE {name} FORCE ROW LEVEL SECURITY"))
            bind.execute(sa.text(f"CREATE POLICY tenant_isolation ON {name} USING (tenant_id::text = current_setting('app.tenant_id', true)) "
                                 "WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))"))


def downgrade():
    raise RuntimeError("Pas de downgrade : restaurer depuis une sauvegarde (voir docs/backup-restore.md)")
