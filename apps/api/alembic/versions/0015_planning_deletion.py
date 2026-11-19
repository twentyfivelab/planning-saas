"""suppression logique d'un planning (confirmée par mot de passe), droit dédié, trace protégée en base"""
import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"


def upgrade():
    import sys
    from pathlib import Path
    sys.path[:0] = [str(Path(__file__).resolve().parents[2])]
    from app.rbac import PERMISSIONS, ROLES

    bind = op.get_bind()
    for col, typ in (("deleted_at", "timestamptz"), ("deleted_by", "uuid"), ("deleted_by_name", "varchar(200)"), ("deletion_archive", "jsonb")):
        bind.execute(sa.text(f"ALTER TABLE planning_periods ADD COLUMN IF NOT EXISTS {col} {typ}"))
    # droit dédié, synchronisé avec rbac.py (propriétaire et administrateur)
    for code in PERMISSIONS:
        bind.execute(sa.text("INSERT INTO permissions(code) VALUES (:c) ON CONFLICT DO NOTHING"), {"c": code})
    for code, (label, perms) in ROLES.items():
        bind.execute(sa.text("INSERT INTO roles(code, label) VALUES (:c, :l) ON CONFLICT (code) DO UPDATE SET label = :l"), {"c": code, "l": label})
        bind.execute(sa.text("DELETE FROM role_permissions WHERE role = :r"), {"r": code})
        for perm in perms:
            bind.execute(sa.text("INSERT INTO role_permissions(role, permission) VALUES (:r, :p)"), {"r": code, "p": perm})
    # trace protégée : un planning supprimé ne peut plus être modifié dans ses champs de suppression, ni supprimé ; l'entrée du journal
    # « period.deleted » ne peut être ni modifiée ni effacée. Seule exception : l'effacement RGPD, marqué explicitement dans sa transaction
    # (app.gdpr_erasure), ou la purge d'un tenant de test (app.tenant_purge).
    bind.execute(sa.text("""
        CREATE OR REPLACE FUNCTION planning_deletion_protected() RETURNS trigger AS $$
        BEGIN
          IF coalesce(current_setting('app.gdpr_erasure', true), '') = 'on' OR coalesce(current_setting('app.tenant_purge', true), '') = 'on' THEN
            RETURN COALESCE(NEW, OLD);
          END IF;
          IF TG_OP = 'DELETE' AND OLD.deleted_at IS NOT NULL THEN
            RAISE EXCEPTION 'Un planning supprimé est conservé pour la traçabilité : il ne peut pas être effacé';
          END IF;
          IF TG_OP = 'UPDATE' AND OLD.deleted_at IS NOT NULL AND (NEW.deleted_at IS DISTINCT FROM OLD.deleted_at OR NEW.deleted_by IS DISTINCT FROM OLD.deleted_by
             OR NEW.deleted_by_name IS DISTINCT FROM OLD.deleted_by_name OR NEW.deletion_archive IS DISTINCT FROM OLD.deletion_archive) THEN
            RAISE EXCEPTION 'La trace de suppression d''un planning est immuable';
          END IF;
          RETURN COALESCE(NEW, OLD);
        END $$ LANGUAGE plpgsql"""))
    bind.execute(sa.text("DROP TRIGGER IF EXISTS trg_planning_deletion ON planning_periods"))
    bind.execute(sa.text("CREATE TRIGGER trg_planning_deletion BEFORE UPDATE OR DELETE ON planning_periods FOR EACH ROW EXECUTE FUNCTION planning_deletion_protected()"))
    bind.execute(sa.text("""
        CREATE OR REPLACE FUNCTION audit_deletion_trace_protected() RETURNS trigger AS $$
        BEGIN
          IF coalesce(current_setting('app.gdpr_erasure', true), '') = 'on' OR coalesce(current_setting('app.tenant_purge', true), '') = 'on' THEN
            RETURN COALESCE(NEW, OLD);
          END IF;
          IF OLD.action = 'period.deleted' THEN
            RAISE EXCEPTION 'La trace de suppression d''un planning ne peut être ni modifiée ni effacée';
          END IF;
          RETURN COALESCE(NEW, OLD);
        END $$ LANGUAGE plpgsql"""))
    bind.execute(sa.text("DROP TRIGGER IF EXISTS trg_audit_deletion_trace ON audit_logs"))
    bind.execute(sa.text("CREATE TRIGGER trg_audit_deletion_trace BEFORE UPDATE OR DELETE ON audit_logs FOR EACH ROW EXECUTE FUNCTION audit_deletion_trace_protected()"))


def downgrade():
    raise RuntimeError("Pas de downgrade : restaurer depuis une sauvegarde (voir docs/backup-restore.md)")
