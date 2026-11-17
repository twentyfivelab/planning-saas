"""plannings existants : pondérations réellement utilisées par le calcul qui a produit leurs affectations (conditions de génération)"""
import json

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"


def upgrade():
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, frozen_params FROM planning_periods WHERE frozen_source = 'mise_en_place' AND frozen_params IS NOT NULL")).all()
    for pid, fp in rows:
        # calcul à l'origine du plus grand nombre d'affectations actuelles du planning
        run = bind.execute(sa.text("SELECT run_id FROM assignments WHERE period_id = :p AND run_id IS NOT NULL GROUP BY run_id ORDER BY count(*) DESC LIMIT 1"),
                           {"p": pid}).scalar()
        if run is None:
            continue
        report = bind.execute(sa.text("SELECT report FROM optimization_results WHERE run_id = :r ORDER BY id LIMIT 1"), {"r": run}).scalar()
        weights = (report or {}).get("weights_used") or (report or {}).get("weights")
        if not weights:
            continue
        fp = dict(fp)
        cfg = dict(fp.get("config") or {})
        cfg["weights"] = {k: int(v) for k, v in weights.items()}
        if report.get("levels"):
            cfg["hierarchical"] = not (len(report["levels"]) == 1 and report["levels"][0].get("level") == "pondere")
        fp["config"] = cfg
        fp["generation_run_id"] = str(run)
        bind.execute(sa.text("UPDATE planning_periods SET frozen_params = CAST(:s AS jsonb) WHERE id = :i"), {"s": json.dumps(fp), "i": pid})


def downgrade():
    raise RuntimeError("Pas de downgrade : restaurer depuis une sauvegarde (voir docs/backup-restore.md)")
