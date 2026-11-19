"""planning supprimé figé en base : aucun shift ni aucune affectation ne peut y être écrit (défaut constaté le 19/11/2026 : un calcul
terminé après la suppression avait écrit dans le planning supprimé)"""
import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"


def upgrade():
    bind = op.get_bind()
    bind.execute(sa.text("""
        CREATE OR REPLACE FUNCTION deleted_period_frozen() RETURNS trigger AS $$
        BEGIN
          IF coalesce(current_setting('app.gdpr_erasure', true), '') = 'on' OR coalesce(current_setting('app.tenant_purge', true), '') = 'on' THEN
            RETURN NEW;
          END IF;
          IF EXISTS (SELECT 1 FROM planning_periods p WHERE p.id = NEW.period_id AND p.deleted_at IS NOT NULL) THEN
            RAISE EXCEPTION 'Planning supprimé : aucun shift ni aucune affectation ne peut y être enregistré';
          END IF;
          RETURN NEW;
        END $$ LANGUAGE plpgsql"""))
    for t in ("shifts", "assignments"):
        bind.execute(sa.text(f"DROP TRIGGER IF EXISTS trg_{t}_deleted_period ON {t}"))
        bind.execute(sa.text(f"CREATE TRIGGER trg_{t}_deleted_period BEFORE INSERT OR UPDATE ON {t} FOR EACH ROW EXECUTE FUNCTION deleted_period_frozen()"))


def downgrade():
    raise RuntimeError("Pas de downgrade : restaurer depuis une sauvegarde (voir docs/backup-restore.md)")
