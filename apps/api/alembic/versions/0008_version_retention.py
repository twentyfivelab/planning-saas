"""conservation configurable des versions automatiques ; permission d'administration du planning"""
import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"


def upgrade():
    import sys
    from pathlib import Path
    sys.path[:0] = [str(Path(__file__).resolve().parents[2])]
    from app.rbac import PERMISSIONS, ROLES

    bind = op.get_bind()
    bind.execute(sa.text("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS version_keep_per_month integer DEFAULT 20"))
    bind.execute(sa.text("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS version_max_age_days integer"))
    for name, stmt in {
        "ck_tenant_version_keep": "ALTER TABLE tenants ADD CONSTRAINT ck_tenant_version_keep CHECK (version_keep_per_month IS NULL OR version_keep_per_month >= 2)",
        "ck_tenant_version_age": "ALTER TABLE tenants ADD CONSTRAINT ck_tenant_version_age CHECK (version_max_age_days IS NULL OR version_max_age_days >= 1)",
    }.items():
        if not bind.execute(sa.text("select 1 from pg_constraint where conname=:n"), {"n": name}).scalar():
            bind.execute(sa.text(stmt))
    for code in PERMISSIONS:
        bind.execute(sa.text("INSERT INTO permissions(code) VALUES (:c) ON CONFLICT DO NOTHING"), {"c": code})
    for code, (label, perms) in ROLES.items():
        bind.execute(sa.text("INSERT INTO roles(code, label) VALUES (:c, :l) ON CONFLICT (code) DO UPDATE SET label = :l"), {"c": code, "l": label})
        bind.execute(sa.text("DELETE FROM role_permissions WHERE role = :r"), {"r": code})
        for perm in perms:
            bind.execute(sa.text("INSERT INTO role_permissions(role, permission) VALUES (:r, :p)"), {"r": code, "p": perm})


def downgrade():
    raise RuntimeError("Pas de downgrade : restaurer depuis une sauvegarde (voir docs/backup-restore.md)")
