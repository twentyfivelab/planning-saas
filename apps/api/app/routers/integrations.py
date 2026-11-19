"""Intégration d'un ajout (nouvelle marque, nouveau collaborateur) au planning EXISTANT d'un mois.

Deux choix, toujours explicites et limités au mois indiqué :
- « Recalculer tout le planning » : nouvelle génération du mois (paramètres conservés par le planning, besoins du mois, contraintes
  habituelles, affectations verrouillées). Le planning initial est conservé en version « Avant intégration de … » ; le résultat est une
  nouvelle version comparable ; un échec ou une annulation laisse le planning initial actif (résultat d'enregistrement du calcul). Rien
  n'est publié. Pour une marque, besoins, horaires, sites et budget du mois doivent être renseignés avant le calcul.
- « Ajouter les shifts manuellement » : aucune affectation créée ; un suivi de couverture (marque) est affiché dans le planning, calculé
  en direct à partir des besoins du mois, des shifts placés, des affectations et des conflits.

Le choix est enregistré (table period_integrations) et inscrit dans l'historique avec son auteur. Aucun autre mois n'est lu pour décision
ni modifié. Un collaborateur ajouté n'a jamais de quota inventé : seul son nombre de shifts attribués est affiché."""
import uuid
from datetime import date, datetime, timezone
from typing import List, Literal, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from planning_solver.timecalc import shift_hours

from .. import models as m
from ..deps import Ctx, audit, get_or_404, require
from ..period_state import ensure_editable, statuses
from ..services_bridge import brand_schedules, build_input
from .months import MONTHS_FR

router = APIRouter(tags=["intégration d'un ajout au planning"])

CHOICE_LABEL = {"recalculate": "Recalculer tout le planning", "manual": "Ajouter les shifts manuellement"}


def _label(p: m.PlanningPeriod) -> str:
    return f"{MONTHS_FR[p.start_date.month - 1].lower()} {p.start_date.year}"


def _today(ctx: Ctx) -> date:
    t = ctx.db.get(m.Tenant, ctx.tenant_id)
    try:
        tz = ZoneInfo(t.timezone if t and t.timezone else "Europe/Zurich")
    except Exception:  # noqa: BLE001
        tz = ZoneInfo("Europe/Zurich")
    return datetime.now(tz).date()


def _brand(ctx: Ctx, code: str) -> m.Brand:
    b = ctx.db.scalar(select(m.Brand).where(m.Brand.code == code))
    if b is None:
        raise HTTPException(404, "Marque inconnue")
    return b


def _employee(ctx: Ctx, eid) -> m.Employee:
    e = get_or_404(ctx, m.Employee, eid)
    if e.deleted_at is not None or not e.active:
        raise HTTPException(422, f"{e.name} n'est pas disponible (inactif ou supprimé de l'équipe).")
    return e


def _entity(ctx: Ctx, kind: str, brand_code: Optional[str], employee_id) -> dict:
    if kind == "brand":
        if not brand_code:
            raise HTTPException(422, "Marque à préciser")
        b = _brand(ctx, brand_code)
        return {"kind": "brand", "code": b.code, "name": b.name, "brand": b}
    if not employee_id:
        raise HTTPException(422, "Collaborateur à préciser")
    e = _employee(ctx, employee_id)
    return {"kind": "employee", "id": str(e.id), "name": e.name, "employee": e}


def _available_in(ctx: Ctx, p: m.PlanningPeriod, ent: dict) -> bool:
    """L'ajout concerne-t-il ce mois ? Marque : non archivée et non désactivée ce mois. Collaborateur : contrat non terminé avant le mois."""
    first = p.start_date.replace(day=1)
    if ent["kind"] == "brand":
        b = ent["brand"]
        if b.archived_from and b.archived_from <= first:
            return False
        row = ctx.db.scalar(select(m.PeriodBrand).where(m.PeriodBrand.period_id == p.id, m.PeriodBrand.brand_code == b.code))
        return row is None or row.active
    contracts = list(ctx.db.scalars(select(m.EmploymentContract).where(m.EmploymentContract.employee_id == ent["employee"].id)))
    return not (contracts and all(c.end_date is not None and c.end_date < p.start_date for c in contracts))


def _existing(ctx: Ctx, p: m.PlanningPeriod, ent: dict) -> Optional[m.PeriodIntegration]:
    q = select(m.PeriodIntegration).where(m.PeriodIntegration.period_id == p.id, m.PeriodIntegration.kind == ent["kind"])
    q = q.where(m.PeriodIntegration.brand_code == ent["code"]) if ent["kind"] == "brand" else q.where(m.PeriodIntegration.employee_id == ent["employee"].id)
    return ctx.db.scalar(q.order_by(m.PeriodIntegration.created_at.desc()).limit(1))


@router.get("/integrations/candidates")
def candidates(brand_code: Optional[str] = None, employee_id: Optional[uuid.UUID] = None, ctx: Ctx = Depends(require("planning.edit"))):
    """Plannings existants (en cours ou à venir, non archivés, non supprimés, avec des affectations) que l'ajout concerne. Lecture seule."""
    ent = _entity(ctx, "brand" if brand_code else "employee", brand_code, employee_id)
    today = _today(ctx)
    periods = list(ctx.db.scalars(select(m.PlanningPeriod).where(m.PlanningPeriod.deleted_at.is_(None), m.PlanningPeriod.archived_at.is_(None),
                                                                 m.PlanningPeriod.end_date >= today).order_by(m.PlanningPeriod.start_date)))
    st = statuses(ctx.db, periods)
    out = []
    for p in periods:
        if not st[p.id]["assignments"] or not _available_in(ctx, p, ent):
            continue
        prev = _existing(ctx, p, ent)
        out.append({"period_id": str(p.id), "name": p.name, "label": _label(p), "month": p.start_date.strftime("%Y-%m"), "status_label": st[p.id]["status_label"],
                    "assignments": st[p.id]["assignments"], "published": st[p.id]["status"] == "published",
                    "already": {"choice": prev.choice, "choice_label": CHOICE_LABEL[prev.choice]} if prev else None})
    return {"entity": {k: v for k, v in ent.items() if k in ("kind", "code", "id", "name")}, "periods": out}


def _readiness(ctx: Ctx, p: m.PlanningPeriod, b: m.Brand) -> dict:
    """Ce qui manque à une marque pour être calculée dans ce mois (besoins, horaires, sites, budget), avec où le renseigner."""
    inp = build_input(ctx.db, p)
    slots = [s for s in inp.slots if b.code in s.allocations]
    sched = brand_schedules(ctx.db).get(b.code, [])
    first = p.start_date.replace(day=1)
    bud = ctx.db.scalar(select(m.MonthlyBudget).where(m.MonthlyBudget.brand_code == b.code, m.MonthlyBudget.month == first))
    missing = []
    if not sched:
        missing.append({"code": "schedules", "text": f"Aucun horaire n'est défini pour {b.name}.", "where": "catalog"})
    if not slots:
        missing.append({"code": "needs", "text": f"Aucun besoin (jours d'animation, site et horaire) n'est défini pour {b.name} en {_label(p)}.", "where": "catalog"})
    sites = sorted({s.site for s in slots})
    if slots and not sites:
        missing.append({"code": "sites", "text": f"Aucun site n'est associé aux besoins de {b.name}.", "where": "catalog"})
    if bud is None:
        missing.append({"code": "budget", "text": f"Aucun budget n'est saisi pour {b.name} en {_label(p)}.", "where": "budget"})
    return {"brand": b.code, "name": b.name, "ready": not missing, "missing": missing, "shifts": len(slots), "sites": sites,
            "base_minutes": b.base_budget_minutes, "budget_minutes": bud.target_minutes if bud else None,
            "need_minutes": sum(s.allocations[b.code] for s in slots)}


@router.get("/periods/{pid}/integrations/readiness")
def readiness(pid: str, brand_code: str, ctx: Ctx = Depends(require("planning.read"))):
    p = get_or_404(ctx, m.PlanningPeriod, pid)
    return _readiness(ctx, p, _brand(ctx, brand_code))


class ChooseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["brand", "employee"]
    brand_code: Optional[str] = Field(None, max_length=64)
    employee_id: Optional[uuid.UUID] = None
    choice: Literal["recalculate", "manual"]
    time_limit_s: float = Field(30, gt=0, le=600)
    confirm_replace: bool = False


@router.post("/periods/{pid}/integrations", status_code=201)
def choose(pid: str, body: ChooseIn, ctx: Ctx = Depends(require("planning.edit")), idempotency_key: Optional[str] = Header(None, max_length=100)):
    p = get_or_404(ctx, m.PlanningPeriod, pid)
    ensure_editable(ctx.db, p.id)
    ent = _entity(ctx, body.kind, body.brand_code, body.employee_id)
    if not _available_in(ctx, p, ent):
        raise HTTPException(409, detail={"code": "not_available", "message": f"{ent['name']} ne concerne pas le planning de {_label(p)} (archivé, désactivé ce mois ou contrat terminé)."})
    roster_added = False
    if ent["kind"] == "employee":  # l'ajout fait partie de l'effectif de CE mois uniquement (choix explicite) ; aucune affectation créée
        e = ent["employee"]
        row = ctx.db.scalar(select(m.PeriodEmployee).where(m.PeriodEmployee.period_id == p.id, m.PeriodEmployee.employee_id == e.id))
        if row is None:
            ctx.db.add(m.PeriodEmployee(tenant_id=ctx.tenant_id, period_id=p.id, employee_id=e.id, included=True, reason="Intégré après la création du planning"))
            roster_added = True
        elif not row.included:
            row.included, row.reason, roster_added = True, "Intégré après la création du planning", True
        ctx.db.flush()
    run_id = None
    if body.choice == "recalculate":
        if ent["kind"] == "brand":
            r = _readiness(ctx, p, ent["brand"])
            if not r["ready"]:
                raise HTTPException(409, detail={"code": "not_ready", "missing": r["missing"],
                                                 "message": "Informations à compléter avant le calcul : " + " ".join(x["text"] for x in r["missing"]) + " Aucun calcul n'a été lancé."})
        from .planning import RunIn, start_run
        res = start_run(str(p.id), RunIn(kind="full", time_limit_s=body.time_limit_s, confirm_replace=body.confirm_replace, params="frozen"), ctx, idempotency_key)
        run = ctx.db.get(m.OptimizationRun, uuid.UUID(res["run_id"]))
        run.config = {**(run.config or {}), "integration": {"kind": ent["kind"], "name": ent["name"]}}  # versions nommées d'après l'ajout
        run_id = run.id
    it = m.PeriodIntegration(tenant_id=ctx.tenant_id, period_id=p.id, kind=ent["kind"], brand_code=ent.get("code"),
                             employee_id=ent["employee"].id if ent["kind"] == "employee" else None, choice=body.choice, run_id=run_id, chosen_by=ctx.user.id)
    ctx.db.add(it)
    ctx.db.flush()
    if ent["kind"] == "brand" and body.choice == "manual":  # état initial : référence des notifications (aucune envoyée au choix lui-même)
        from ..integration_watch import record
        record(ctx.db, it, p, ent["name"], _coverage(ctx, p, ent["code"]), notify=False)
    audit(ctx, "integration.chosen", "period", p.id, {"period_id": str(p.id), "period": p.name, "label": _label(p), "kind": ent["kind"], "name": ent["name"],
                                                       "brand": ent.get("code"), "employee_id": ent.get("id"), "choice": body.choice,
                                                       "choice_label": CHOICE_LABEL[body.choice], "run_id": str(run_id) if run_id else None,
                                                       "roster_added": roster_added})
    return {"integration_id": str(it.id), "choice": body.choice, "run_id": str(run_id) if run_id else None, "period_id": str(p.id), "label": _label(p)}


def _coverage(ctx: Ctx, p: m.PlanningPeriod, code: str, inp=None) -> dict:
    from ..coverage import brand_coverage
    return brand_coverage(ctx.db, p, code, inp)


@router.get("/periods/{pid}/integrations")
def list_integrations(pid: str, ctx: Ctx = Depends(require("planning.read"))):
    """Suivis actifs du mois (choix « Ajouter les shifts manuellement »), recalculés à chaque lecture."""
    p = get_or_404(ctx, m.PlanningPeriod, pid)
    rows = list(ctx.db.scalars(select(m.PeriodIntegration).where(m.PeriodIntegration.period_id == p.id, m.PeriodIntegration.choice == "manual",
                                                                 m.PeriodIntegration.dismissed_at.is_(None)).order_by(m.PeriodIntegration.created_at)))
    if not rows:
        return {"items": []}
    inp = build_input(ctx.db, p)
    brands = {b.code: b.name for b in ctx.db.scalars(select(m.Brand))}
    out, seen = [], set()
    for it in rows:
        key = (it.kind, it.brand_code or str(it.employee_id))
        if key in seen:
            continue
        seen.add(key)
        base = {"id": str(it.id), "kind": it.kind, "created_at": it.created_at.isoformat() if it.created_at else None}
        if it.kind == "brand":
            out.append({**base, "brand": it.brand_code, "name": brands.get(it.brand_code, it.brand_code), "coverage": _coverage(ctx, p, it.brand_code, inp)})
        else:
            e = ctx.db.get(m.Employee, it.employee_id)
            if e is None:
                continue
            n, mins = ctx.db.execute(select(func.count(), func.coalesce(func.sum(m.Shift.effective_minutes), 0)).select_from(m.Assignment)
                                     .join(m.Shift, m.Shift.id == m.Assignment.shift_id).where(m.Assignment.period_id == p.id, m.Assignment.employee_id == e.id)).one()
            out.append({**base, "employee_id": str(e.id), "name": e.name, "assigned": int(n), "minutes": int(mins)})
    return {"items": out}


class PlaceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slot_key: str = Field(min_length=1, max_length=200)


@router.post("/periods/{pid}/integrations/{iid}/place", status_code=201)
def place(pid: str, iid: str, body: PlaceIn, ctx: Ctx = Depends(require("planning.edit"))):
    """Place un besoin de la marque dans le planning (shift sans collaborateur), à attribuer ensuite avec les contrôles habituels."""
    p = get_or_404(ctx, m.PlanningPeriod, pid)
    ensure_editable(ctx.db, p.id)
    it = get_or_404(ctx, m.PeriodIntegration, iid)
    if it.period_id != p.id or it.kind != "brand":
        raise HTTPException(404, "Introuvable")
    s = next((x for x in build_input(ctx.db, p).slots if x.id == body.slot_key and it.brand_code in x.allocations), None)
    if s is None:
        raise HTTPException(422, "Ce besoin n'existe pas (ou plus) pour cette marque ce mois-ci.")
    sh = ctx.db.scalar(select(m.Shift).where(m.Shift.period_id == p.id, m.Shift.slot_key == s.id))
    if sh is not None:
        return {"shift_id": str(sh.id), "day": sh.day.isoformat(), "already": True}
    h = shift_hours(s.day, s.start, s.end, s.break_minutes)
    sh = m.Shift(tenant_id=ctx.tenant_id, period_id=p.id, slot_key=s.id, day=s.day, site_code=s.site, start_time=s.start, end_time=s.end,
                 break_minutes=s.break_minutes, presence_minutes=h.presence_minutes, effective_minutes=h.effective_minutes)
    ctx.db.add(sh)
    ctx.db.flush()
    from ..history import shift_context
    audit(ctx, "shift.placed", "shift", sh.id, {"period_id": str(p.id), "day": s.day.isoformat(), "start": s.start.isoformat(), "end": s.end.isoformat(),
                                                **shift_context(ctx.db, sh), "brands": [it.brand_code]})
    return {"shift_id": str(sh.id), "day": s.day.isoformat(), "already": False}


@router.post("/periods/{pid}/integrations/{iid}/dismiss")
def dismiss(pid: str, iid: str, ctx: Ctx = Depends(require("planning.edit"))):
    """Masque le suivi (il n'est pas supprimé : le choix reste dans l'historique)."""
    p = get_or_404(ctx, m.PlanningPeriod, pid)
    it = get_or_404(ctx, m.PeriodIntegration, iid)
    if it.period_id != p.id:
        raise HTTPException(404, "Introuvable")
    if it.dismissed_at is None:
        it.dismissed_at = datetime.now(timezone.utc)
        audit(ctx, "integration.dismissed", "period", p.id, {"period_id": str(p.id), "integration_id": str(it.id)})
    return {"dismissed": True}


__all__: List[str] = ["router"]
