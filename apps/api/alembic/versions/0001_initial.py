"""schéma initial + RLS + rôle applicatif + fonctions d'authentification"""
import os

import sqlalchemy as sa
from alembic import op

from app.models import Base, TENANT_TABLES
from app.rbac import PERMISSIONS, ROLES

revision = "0001"
down_revision = None


def upgrade():
    bind = op.get_bind()
    Base.metadata.create_all(bind)

    app_user = os.environ.get("APP_DB_USER", "planning_app")
    app_pwd = os.environ.get("APP_DB_PASSWORD", "")
    exists = bind.execute(sa.text("select 1 from pg_roles where rolname=:r"), {"r": app_user}).scalar()
    if not exists:
        if not app_pwd:
            raise RuntimeError("APP_DB_PASSWORD requis pour créer le rôle applicatif non-superuser")
        ddl = bind.execute(sa.text("select format('CREATE ROLE %I LOGIN PASSWORD %L NOSUPERUSER NOBYPASSRLS', "
                                   "cast(:u as text), cast(:p as text))"), {"u": app_user, "p": app_pwd}).scalar()
        bind.exec_driver_sql(ddl)
    bind.execute(sa.text(f'GRANT USAGE ON SCHEMA public TO "{app_user}"'))
    bind.execute(sa.text(f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO "{app_user}"'))
    # tables de référence globales : lecture seule
    for t in ("roles", "permissions", "role_permissions"):
        bind.execute(sa.text(f'REVOKE INSERT, UPDATE, DELETE ON {t} FROM "{app_user}"'))
    # le journal d'audit est append-only pour l'application
    bind.execute(sa.text(f'REVOKE UPDATE, DELETE ON audit_logs FROM "{app_user}"'))

    for t in TENANT_TABLES:
        bind.execute(sa.text(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY"))
        bind.execute(sa.text(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY"))
        bind.execute(sa.text(
            f"CREATE POLICY tenant_isolation ON {t} USING (tenant_id::text = current_setting('app.tenant_id', true)) "
            f"WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))"))
    bind.execute(sa.text("ALTER TABLE tenants ENABLE ROW LEVEL SECURITY"))
    bind.execute(sa.text("ALTER TABLE tenants FORCE ROW LEVEL SECURITY"))
    bind.execute(sa.text(
        "CREATE POLICY tenant_isolation ON tenants USING (id::text = current_setting('app.tenant_id', true)) "
        "WITH CHECK (id::text = current_setting('app.tenant_id', true))"))

    # Connexion : l'e-mail est connu avant le tenant -> fonction SECURITY DEFINER (propriétaire), accès restreint
    bind.execute(sa.text("""
        CREATE FUNCTION auth_lookup_user(p_email text)
        RETURNS TABLE(id uuid, tenant_id uuid, password_hash text, role text, is_active boolean)
        LANGUAGE sql SECURITY DEFINER SET search_path = public AS
        $$ SELECT u.id, u.tenant_id, u.password_hash, u.role, u.is_active FROM users u WHERE u.email = lower(p_email) $$"""))
    bind.execute(sa.text("REVOKE ALL ON FUNCTION auth_lookup_user(text) FROM PUBLIC"))
    bind.execute(sa.text(f'GRANT EXECUTE ON FUNCTION auth_lookup_user(text) TO "{app_user}"'))

    for p in PERMISSIONS:
        bind.execute(sa.text("INSERT INTO permissions(code) VALUES (:c)"), {"c": p})
    for code, (label, perms) in ROLES.items():
        bind.execute(sa.text("INSERT INTO roles(code,label) VALUES (:c,:l)"), {"c": code, "l": label})
        for p in perms:
            bind.execute(sa.text("INSERT INTO role_permissions(role,permission) VALUES (:r,:p)"), {"r": code, "p": p})


def downgrade():
    raise RuntimeError("Pas de downgrade : restaurer depuis une sauvegarde (voir docs/backup-restore.md)")
