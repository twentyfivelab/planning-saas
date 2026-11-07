"""Référentiel juridique configurable, versionné et contrôlable. Les modèles proposés citent leur source officielle ; rien n'est actif
sans décision de l'entreprise, et toute règle reste « à valider » tant qu'un responsable juridique ne l'a pas validée."""
from datetime import date, datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from .. import models as m
from ..deps import Ctx, audit, get_or_404, require

router = APIRouter(tags=["référentiel juridique"])

SECO = "https://www.seco.admin.ch/fr/duree-du-travail-et-du-repos"
COMMENTARY = "https://www.seco.admin.ch/dam/fr/sd-web/HgQABCOvNmQV/OLT-1-2-SECO-AB-2026-FR.pdf"
CCT = "https://www.seco.admin.ch/fr/convention-collectives-de-travail-confederation"
CODES = {"rest_hours", "max_consecutive_days", "weekly_max_minutes", "break_rules"}
# key, code, libellé, régime, paramètres, source, portée (texte lu sur la page officielle citée)
TEMPLATES = [
    {"key": "rest_11h", "code": "rest_hours", "label": "Repos quotidien : 11 heures consécutives", "jurisdiction": None, "params": {"value": 11},
     "source_url": SECO, "note": "Art. 15a LTr, art. 19 OLT 1. Une réduction à 8 h est possible sous conditions : non appliquée automatiquement."},
    {"key": "weekly_45h", "code": "weekly_max_minutes", "label": "Durée maximale hebdomadaire : 45 heures", "jurisdiction": "LTr-45", "params": {"value": 45 * 60},
     "source_url": SECO, "note": "Art. 9 LTr, art. 2 OLT 1 : entreprises industrielles, personnel de bureau, personnel technique, autres employés, personnel de vente des grandes entreprises du commerce de détail."},
    {"key": "weekly_50h", "code": "weekly_max_minutes", "label": "Durée maximale hebdomadaire : 50 heures", "jurisdiction": "LTr-50", "params": {"value": 50 * 60},
     "source_url": SECO, "note": "Art. 9 LTr, art. 2 OLT 1 : tous les autres travailleurs."},
    {"key": "breaks_art15", "code": "break_rules", "label": "Pauses minimales : 15 min (plus de 5 h 30), 30 min (plus de 7 h), 1 h (plus de 9 h)", "jurisdiction": None,
     "params": {"rules": [{"over_minutes": 330, "break_minutes": 15}, {"over_minutes": 420, "break_minutes": 30}, {"over_minutes": 540, "break_minutes": 60}]},
     "source_url": COMMENTARY, "note": "Art. 15 LTr. Les pauses comptent comme travail lorsque le travailleur n'est pas autorisé à quitter sa place : ce point reste à apprécier cas par cas."},
]
BY_KEY = {t["key"]: t for t in TEMPLATES}
REVIEW = {"a_valider": "À valider", "valide": "Validée", "rejete": "Rejetée"}


def _view(c: m.ConstraintDefinition, names: dict) -> dict:
    return {"id": str(c.id), "code": c.code, "kind": c.kind, "jurisdiction": c.jurisdiction, "params": c.params, "version": c.version, "enabled": c.enabled,
            "valid_from": c.valid_from.isoformat() if c.valid_from else None, "valid_to": c.valid_to.isoformat() if c.valid_to else None,
            "source_url": c.source_url, "review_status": c.legal_review_status, "review_label": REVIEW.get(c.legal_review_status, c.legal_review_status),
            "reviewed_by": names.get(c.reviewed_by), "reviewed_at": c.reviewed_at.isoformat() if c.reviewed_at else None, "note": c.exception_reason, "created_at": c.created_at.isoformat() if c.created_at else None}


def _rows(ctx: Ctx) -> list:
    return [c for c in ctx.db.scalars(select(m.ConstraintDefinition).where(m.ConstraintDefinition.scope == "tenant").order_by(m.ConstraintDefinition.code, m.ConstraintDefinition.version))
            if c.code in CODES]


@router.get("/legal/rules")
def rules(ctx: Ctx = Depends(require("referential.read"))):
    names = {u.id: u.name for u in ctx.db.scalars(select(m.User))}
    rows = _rows(ctx)
    active = {(c.code, c.jurisdiction or None) for c in rows if c.enabled}
    general = {c.code for c in rows if c.enabled}  # repos, pauses : une seule valeur active pour le tenant, quelle que soit sa juridiction
    regimes = sorted({c.legal_regime for c in ctx.db.scalars(select(m.EmploymentContract)) if c.legal_regime})
    return {"rules": [_view(c, names) for c in rows], "regimes": regimes, "pending_review": sum(1 for c in rows if c.enabled and c.legal_review_status != "valide"),
            "templates": [{**t, "active": (t["code"], t["jurisdiction"]) in active or (t["jurisdiction"] is None and t["code"] in general)} for t in TEMPLATES],
            "sources": [{"label": "SECO — Durée du travail et du repos", "url": SECO}, {"label": "SECO — Commentaire de la loi sur le travail et des ordonnances 1 et 2", "url": COMMENTARY},
                        {"label": "SECO — Conventions collectives de travail", "url": CCT}]}


class FromTemplateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    template: str = Field(max_length=32)
    valid_from: Optional[date] = None


@router.post("/legal/rules/from-template", status_code=201)
def from_template(body: FromTemplateIn, ctx: Ctx = Depends(require("rules.write"))):
    """Active un modèle. La règle est exécutée dès la prochaine génération, mais reste « à valider » par un responsable juridique."""
    t = BY_KEY.get(body.template)
    if t is None:
        raise HTTPException(422, "Modèle inconnu")
    prior = [c for c in _rows(ctx) if c.code == t["code"] and (t["jurisdiction"] is None or (c.jurisdiction or None) == t["jurisdiction"])]
    for c in prior:
        if c.enabled:
            raise HTTPException(409, f"Cette règle existe déjà (version {c.version}) : modifiez-la pour en créer une nouvelle version.")
    c = m.ConstraintDefinition(tenant_id=ctx.tenant_id, kind="legal", code=t["code"], scope="tenant", params=t["params"], jurisdiction=t["jurisdiction"], source_url=t["source_url"],
                               version=max((p.version for p in prior), default=0) + 1, valid_from=body.valid_from, enabled=True, enabled_by=ctx.user.id, legal_review_status="a_valider",
                               exception_reason=t["note"])
    ctx.db.add(c)
    ctx.db.flush()
    audit(ctx, "legal.activate", "constraint", c.id, {"template": t["key"], "code": t["code"], "params": t["params"], "jurisdiction": t["jurisdiction"]})
    return _view(c, {})


class RuleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: Literal["rest_hours", "max_consecutive_days", "weekly_max_minutes", "break_rules"]
    jurisdiction: Optional[str] = Field(None, max_length=64)
    params: dict
    valid_from: Optional[date] = None
    source_url: Optional[str] = Field(None, max_length=300)
    note: Optional[str] = Field(None, max_length=1000)


def _check_params(code: str, p: dict) -> None:
    try:
        if code == "break_rules":
            assert p["rules"] and all(int(x["over_minutes"]) > 0 and 0 <= int(x["break_minutes"]) <= 240 for x in p["rules"])
        else:
            v = int(p["value"])
            limit = {"rest_hours": 24, "max_consecutive_days": 31, "weekly_max_minutes": 7 * 24 * 60}[code]
            assert 0 < v <= limit
    except (KeyError, TypeError, ValueError, AssertionError):
        raise HTTPException(422, "Paramètres invalides pour cette règle.")


@router.post("/legal/rules", status_code=201)
def create_version(body: RuleIn, ctx: Ctx = Depends(require("rules.write"))):
    """Nouvelle version d'une règle (ou première version d'un régime) : la version précédente est close à la veille, jamais réécrite,
    et la nouvelle repart « à valider »."""
    _check_params(body.code, body.params)
    prior = [c for c in _rows(ctx) if c.code == body.code and (c.jurisdiction or None) == (body.jurisdiction or None)]
    start = body.valid_from
    for c in prior:
        if c.enabled:
            if start is None:
                c.enabled = False
            else:
                c.valid_to = start - timedelta(days=1)
    c = m.ConstraintDefinition(tenant_id=ctx.tenant_id, kind="legal", code=body.code, scope="tenant", params=body.params, jurisdiction=body.jurisdiction or None, source_url=body.source_url,
                               version=max((p.version for p in prior), default=0) + 1, valid_from=start, enabled=True, enabled_by=ctx.user.id, legal_review_status="a_valider", exception_reason=body.note)
    ctx.db.add(c)
    ctx.db.flush()
    audit(ctx, "legal.new_version", "constraint", c.id, {"code": body.code, "version": c.version, "params": body.params, "jurisdiction": body.jurisdiction})
    return _view(c, {})


class ReviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["a_valider", "valide", "rejete"]
    note: Optional[str] = Field(None, max_length=1000)


@router.post("/legal/rules/{rid}/review")
def review(rid: str, body: ReviewIn, ctx: Ctx = Depends(require("legal.review"))):
    """Validation par un responsable juridique : elle est nominative et tracée ; une règle rejetée n'est plus exécutée."""
    c = get_or_404(ctx, m.ConstraintDefinition, rid)
    if c.code not in CODES:
        raise HTTPException(422, "Cette règle n'appartient pas au référentiel juridique.")
    before = c.legal_review_status
    c.legal_review_status, c.reviewed_by, c.reviewed_at = body.status, ctx.user.id, datetime.now(timezone.utc)
    if body.status == "rejete":
        c.enabled = False
    if body.note:
        c.exception_reason = body.note
    ctx.db.flush()
    audit(ctx, "legal.review", "constraint", c.id, {"code": c.code, "version": c.version, "before": before, "after": body.status, "note": body.note})
    return _view(c, {ctx.user.id: ctx.user.name})


class EnableIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool


@router.post("/legal/rules/{rid}/enabled")
def set_enabled(rid: str, body: EnableIn, ctx: Ctx = Depends(require("rules.write"))):
    c = get_or_404(ctx, m.ConstraintDefinition, rid)
    if c.code not in CODES:
        raise HTTPException(422, "Cette règle n'appartient pas au référentiel juridique.")
    c.enabled = body.enabled
    audit(ctx, "legal.enable" if body.enabled else "legal.disable", "constraint", c.id, {"code": c.code, "version": c.version})
    ctx.db.flush()
    return _view(c, {})
