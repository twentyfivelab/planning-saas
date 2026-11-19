"""Statut réel d'un planning mensuel (déduit des données enregistrées, jamais saisi à la main) et protection des plannings archivés."""
from fastapi import HTTPException
from sqlalchemy import func, select

from . import models as m
from .versioning import current_map, snapshot_map

LABELS = {"draft": "Brouillon", "generated": "Généré", "in_review": "En cours de validation", "validated": "Validé", "published": "Publié", "archived": "Archivé"}
_RANK = {"in_review": 1, "validated": 2, "published": 3}


def statuses(db, periods) -> dict:
    """Brouillon = aucune affectation ; Généré = des affectations existent ; En cours de validation / Validé / Publié = état de la version la plus
    avancée ; Archivé = archivé (consultable, figé). `changed_since` signale un planning modifié depuis sa validation ou sa publication."""
    ids = [p.id for p in periods]
    if not ids:
        return {}
    n_asg = dict(db.execute(select(m.Assignment.period_id, func.count()).where(m.Assignment.period_id.in_(ids)).group_by(m.Assignment.period_id)).all())
    best: dict = {}
    for v in db.scalars(select(m.ScheduleVersion).where(m.ScheduleVersion.period_id.in_(ids), m.ScheduleVersion.state.in_(list(_RANK)))):
        b = best.get(v.period_id)
        if b is None or (_RANK[v.state], v.number) > (_RANK[b.state], b.number):
            best[v.period_id] = v
    out = {}
    for p in periods:
        v = best.get(p.id)
        st = "archived" if p.archived_at else v.state if v is not None else "generated" if n_asg.get(p.id) else "draft"
        changed = bool(v is not None and not p.archived_at and snapshot_map(v.snapshot or []) != current_map(db, p.id))
        out[p.id] = {"status": st, "status_label": LABELS[st], "assignments": int(n_asg.get(p.id, 0)), "changed_since": changed}
    return out


def has_official_version(db, period_id) -> bool:
    """Une version validée ou publiée existe : elle ne doit jamais être remplacée silencieusement."""
    return db.scalar(select(m.ScheduleVersion.id).where(m.ScheduleVersion.period_id == period_id, m.ScheduleVersion.state.in_(("validated", "published"))).limit(1)) is not None


def ensure_editable(db, period_id) -> None:
    p = db.get(m.PlanningPeriod, period_id)
    if p is not None and p.deleted_at is not None:
        raise HTTPException(404, "Ce planning a été supprimé : il ne peut plus être modifié.")
    if p is not None and p.archived_at is not None:
        raise HTTPException(409, f"{p.name} est archivé : il reste consultable mais n'est plus modifiable. Désarchivez-le pour le modifier.")
