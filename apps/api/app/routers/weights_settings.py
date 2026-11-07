"""Paramètres → Pondération de l'algorithme : enregistrée en base, transmise au solveur à chaque génération / réoptimisation."""
from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from planning_solver.weights import ADVANCED, ADVANCED_KEYS, ADVANCED_MAX, CRITERIA, DEFAULT_UI, breakdown, engine_weights
from planning_solver.model import DEFAULT_WEIGHTS

from .. import models as m
from ..deps import Ctx, audit, require

router = APIRouter(tags=["paramètres"])
CODE = "weights_ui"


def _row(ctx: Ctx):
    return ctx.db.scalar(select(m.ConstraintDefinition).where(m.ConstraintDefinition.code == CODE, m.ConstraintDefinition.scope == "tenant"))


def _view(ctx: Ctx) -> dict:
    r = _row(ctx)
    p = (r.params if r else None) or {}
    crit, adv = p.get("criteria", {}), p.get("advanced", {})
    eng = engine_weights(crit, adv)
    last = ctx.db.execute(select(m.OptimizationResult, m.PlanningPeriod.name).join(m.OptimizationRun, m.OptimizationRun.id == m.OptimizationResult.run_id)
                          .join(m.PlanningPeriod, m.PlanningPeriod.id == m.OptimizationRun.period_id)
                          .where(m.OptimizationRun.simulation.is_(False))
                          .order_by(m.OptimizationResult.created_at.desc()).limit(1)).first()
    scores = None
    if last is not None and (last[0].report or {}).get("objective"):
        rep = last[0].report
        scores = {"period": last[1], "status": last[0].status, "at": last[0].created_at.isoformat(), "objective": rep["objective"],
                  "by_criterion": breakdown(rep["objective"]), "weights_used": rep.get("weights_used", {})}
    return {"criteria": [{"key": k, "label": label, "description": text, "default": d, "value": int(crit.get(k, d)), "engine": {e: eng[e] for e in engs}}
                         for k, label, d, engs, text in CRITERIA],
            "advanced": [{"key": k, "label": label, "description": text, "default": DEFAULT_WEIGHTS[k], "value": eng[k], "max": ADVANCED_MAX} for k, label, text in ADVANCED],
            "hierarchical": bool(p.get("hierarchical", True)), "last_run": scores, "customised": bool(crit or adv)}


class WeightsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    criteria: Dict[str, int] = {}
    advanced: Dict[str, int] = {}
    hierarchical: Optional[bool] = None


@router.get("/settings/weights")
def get_weights(ctx: Ctx = Depends(require("referential.read"))):
    return _view(ctx)


@router.put("/settings/weights")
def put_weights(body: WeightsIn, ctx: Ctx = Depends(require("rules.write"))):
    """Fusionne les valeurs envoyées avec celles déjà enregistrées (enregistrement automatique curseur par curseur)."""
    bad = [k for k in body.criteria if k not in DEFAULT_UI] + [k for k in body.advanced if k not in ADVANCED_KEYS]
    if bad:
        raise HTTPException(422, f"Critère inconnu : {', '.join(bad)}")
    if any(not 0 <= v <= 100 for v in body.criteria.values()):
        raise HTTPException(422, "Une pondération est comprise entre 0 et 100.")
    if any(not 0 <= v <= ADVANCED_MAX for v in body.advanced.values()):
        raise HTTPException(422, f"Un poids avancé est compris entre 0 et {ADVANCED_MAX}.")
    r = _row(ctx)
    before = dict((r.params if r else None) or {})
    params = {"criteria": {**before.get("criteria", {}), **body.criteria}, "advanced": {**before.get("advanced", {}), **body.advanced},
              "hierarchical": before.get("hierarchical", True) if body.hierarchical is None else body.hierarchical}
    if r is None:
        r = m.ConstraintDefinition(tenant_id=ctx.tenant_id, kind="internal", code=CODE, scope="tenant", params=params, enabled=True,
                                   legal_review_status="a_valider")
        ctx.db.add(r)
    else:
        r.params = params
    ctx.db.flush()
    audit(ctx, "settings.weights", "settings", r.id, {"before": before, "after": params})
    return _view(ctx)


@router.post("/settings/weights/reset")
def reset_weights(ctx: Ctx = Depends(require("rules.write"))):
    r = _row(ctx)
    if r is not None:
        audit(ctx, "settings.weights_reset", "settings", r.id, {"before": r.params})
        ctx.db.delete(r)
        ctx.db.flush()
    return _view(ctx)
