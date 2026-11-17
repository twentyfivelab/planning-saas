"""contexte de génération figé dans chaque version (entrée complète du moteur, empreinte, version du moteur)"""
import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"


def upgrade():
    bind = op.get_bind()
    for stmt in ("ALTER TABLE schedule_versions ADD COLUMN IF NOT EXISTS context jsonb",
                 "ALTER TABLE schedule_versions ADD COLUMN IF NOT EXISTS context_hash varchar(64)",
                 "ALTER TABLE schedule_versions ADD COLUMN IF NOT EXISTS engine_version varchar(32)"):
        bind.execute(sa.text(stmt))
    # versions existantes : contexte NON reconstitué (les données de l'époque ne sont pas connues) -> « contexte incomplet »
    # le contexte d'une version ne peut plus être modifié une fois écrit
    bind.execute(sa.text("""
        CREATE OR REPLACE FUNCTION schedule_version_context_immutable() RETURNS trigger AS $$
        BEGIN
          -- seule exception : l'effacement RGPD (droit à l'effacement), marqué explicitement dans sa transaction
          IF coalesce(current_setting('app.gdpr_erasure', true), '') <> 'on' AND OLD.context IS NOT NULL AND (NEW.context IS DISTINCT FROM OLD.context OR NEW.context_hash IS DISTINCT FROM OLD.context_hash
                                          OR NEW.engine_version IS DISTINCT FROM OLD.engine_version OR NEW.snapshot IS DISTINCT FROM OLD.snapshot) THEN
            RAISE EXCEPTION 'Le contexte et les affectations d''une version sont immuables';
          END IF;
          RETURN NEW;
        END $$ LANGUAGE plpgsql"""))
    bind.execute(sa.text("DROP TRIGGER IF EXISTS trg_schedule_version_context ON schedule_versions"))
    bind.execute(sa.text("CREATE TRIGGER trg_schedule_version_context BEFORE UPDATE ON schedule_versions FOR EACH ROW "
                         "EXECUTE FUNCTION schedule_version_context_immutable()"))


def downgrade():
    raise RuntimeError("Pas de downgrade : restaurer depuis une sauvegarde (voir docs/backup-restore.md)")
