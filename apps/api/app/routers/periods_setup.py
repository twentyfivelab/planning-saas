"""Préparation d'un planning mensuel (assistant) : effectif du mois, marques et budgets, sites, vérification avant génération,
brouillon, archivage. Tout est enregistré par mois : modifier décembre ne touche jamais novembre."""
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, select

from .. import models as m
from ..deps import Ctx, audit, get_or_404, require
from ..period_state import ensure_editable, statuses
from ..services_bridge import assignments_for_validation, brand_schedules, build_input
from .crud import serialize
from .months import month_bounds

router = APIRouter(tags=["préparation du planning mensuel"])


def _period(ctx: Ctx, pid: str) -> m.PlanningPeriod:
    return get_or_404(ctx, m.PlanningPeriod, pid)


def _contract_ended(ctx: Ctx, start) -> dict:
    """Collaborateurs dont TOUS les contrats ont pris fin avant le mois : date de fin (distinct d'une exclusion temporaire)."""
    by: dict = defaultdict(list)
    for c in ctx.db.scalars(select(m.EmploymentContract)):
        by[c.employee_id].append(c)
    return {eid: max(c.end_date for c in cs) for eid, cs in by.items() if cs and all(c.end_date is not None and c.end_date < start for c in cs)}


# ---------- statut, brouillon, archivage ----------
class WizardIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    step: Optional[int] = Field(None, ge=1, le=6)  # None = assistant terminé


@router.patch("/periods/{pid}/wizard")
def wizard_step(pid: str, body: WizardIn, ctx: Ctx = Depends(require("planning.edit"))):
    p = _period(ctx, pid)
    p.wizard_step = body.step
    return {**serialize(p), **statuses(ctx.db, [p])[p.id]}


@router.post("/periods/{pid}/archive")
def archive(pid: str, ctx: Ctx = Depends(require("planning.publish"))):
    p = _period(ctx, pid)
    if p.archived_at is None:
        p.archived_at = datetime.now(timezone.utc)
        audit(ctx, "period.archive", "period", p.id, {"name": p.name})
    return {**serialize(p), **statuses(ctx.db, [p])[p.id]}


@router.post("/periods/{pid}/unarchive")
def unarchive(pid: str, ctx: Ctx = Depends(require("planning.publish"))):
    p = _period(ctx, pid)
    if p.archived_at is not None:
        p.archived_at = None
        audit(ctx, "period.unarchive", "period", p.id, {"name": p.name})
    return {**serialize(p), **statuses(ctx.db, [p])[p.id]}


class ResetIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm_name: str = Field(max_length=100)


@router.post("/periods/{pid}/reset")
def reset_period(pid: str, body: ResetIn, ctx: Ctx = Depends(require("planning.admin"))):
    """Remet UN mois à zéro, en une transaction : affectations, shifts, calculs, versions, heures saisies, effectif, marques et sites du mois, budgets et
    paramètres mensuels. Les autres mois, les fiches, les indisponibilités et le journal d'audit ne changent pas. Refusé si le mois porte une version
    validée ou publiée, des heures validées, ou s'il est archivé. Le mois reste, en brouillon."""
    p = _period(ctx, pid)
    ensure_editable(ctx.db, p.id)
    if body.confirm_name.strip() != p.name:
        raise HTTPException(422, f"Saisissez exactement « {p.name} » pour confirmer.")
    official = ctx.db.scalars(select(m.ScheduleVersion.number).where(m.ScheduleVersion.period_id == p.id, m.ScheduleVersion.state.in_(("in_review", "validated", "published", "superseded")))).all()
    if official:
        raise HTTPException(409, f"{p.name} a des versions soumises, validées ou publiées : il ne peut pas être remis à zéro.")
    if ctx.db.scalar(select(m.TimeEntry.id).where(m.TimeEntry.period_id == p.id, m.TimeEntry.validated_at.is_not(None)).limit(1)) is not None:
        raise HTTPException(409, f"{p.name} a des heures réelles validées : il ne peut pas être remis à zéro.")
    first = p.start_date.replace(day=1)
    counts = {}
    for name, stmt in (
            ("heures saisies", delete(m.TimeEntry).where(m.TimeEntry.period_id == p.id)),
            ("affectations", delete(m.Assignment).where(m.Assignment.period_id == p.id)),
            ("shifts", delete(m.Shift).where(m.Shift.period_id == p.id)),
            ("calculs", delete(m.OptimizationRun).where(m.OptimizationRun.period_id == p.id)),
            ("versions", delete(m.ScheduleVersion).where(m.ScheduleVersion.period_id == p.id)),
            ("effectif", delete(m.PeriodEmployee).where(m.PeriodEmployee.period_id == p.id)),
            ("marques du mois", delete(m.PeriodBrand).where(m.PeriodBrand.period_id == p.id)),
            ("sites du mois", delete(m.PeriodSite).where(m.PeriodSite.period_id == p.id)),
            ("budgets", delete(m.MonthlyBudget).where(m.MonthlyBudget.month == first)),
            ("paramètres mensuels", delete(m.EmployeeMonthParams).where(m.EmployeeMonthParams.month == first))):
        counts[name] = ctx.db.execute(stmt).rowcount
    p.wizard_step = None
    ctx.db.flush()
    ctx.db.expire_all()  # suppressions faites en SQL : aucune donnée retirée ne reste en mémoire
    audit(ctx, "period.reset", "period", p.id, {"period": p.name, "removed": counts})
    return {"period": p.name, "removed": counts}


@router.delete("/periods/{pid}", status_code=204)
def delete_draft(pid: str, ctx: Ctx = Depends(require("planning.edit"))):
    """Seul un BROUILLON (aucune affectation, aucune version) peut être supprimé ; un planning généré se garde ou s'archive."""
    p = _period(ctx, pid)
    if statuses(ctx.db, [p])[p.id]["status"] != "draft" or ctx.db.scalar(select(func.count()).select_from(m.ScheduleVersion).where(m.ScheduleVersion.period_id == p.id)):
        raise HTTPException(409, "Seul un brouillon sans affectation ni version peut être supprimé. Un planning généré peut être archivé.")
    if ctx.db.scalar(select(func.count()).select_from(m.OptimizationRun).where(m.OptimizationRun.period_id == p.id)):
        raise HTTPException(409, "Ce planning a déjà été calculé : il ne peut pas être supprimé, seulement archivé.")
    audit(ctx, "period.delete_draft", "period", p.id, {"name": p.name})
    ctx.db.delete(p)


# ---------- étape 2 : effectif du mois ----------
def _roster(ctx: Ctx, p: m.PlanningPeriod) -> list:
    rows = {r.employee_id: r for r in ctx.db.scalars(select(m.PeriodEmployee).where(m.PeriodEmployee.period_id == p.id))}
    ended = _contract_ended(ctx, p.start_date)
    out = []
    for e in ctx.db.scalars(select(m.Employee).order_by(m.Employee.name)):
        if not e.active:
            state = "inactive"
        elif e.id in ended:
            state = "contract_ended"
        else:
            r = rows.get(e.id)
            state = "excluded" if r is not None and not r.included else "included"
        out.append({"employee_id": str(e.id), "code": e.code, "name": e.name, "state": state, "included": state == "included",
                    "selectable": state in ("included", "excluded"), "reason": rows[e.id].reason if e.id in rows else None,
                    "contract_end": ended[e.id].isoformat() if e.id in ended else None})
    return out


@router.get("/periods/{pid}/roster")
def roster(pid: str, ctx: Ctx = Depends(require("planning.read"))):
    """Effectif du mois. Par défaut, tous les collaborateurs actifs sont retenus. « Contrat terminé » et « Inactif » ne sont pas sélectionnables :
    ce sont des états permanents, distincts d'une exclusion temporaire du mois."""
    p = _period(ctx, pid)
    items = _roster(ctx, p)
    return {"employees": items, "included": sum(1 for x in items if x["included"]), "total": len(items)}


class RosterItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    employee_id: uuid.UUID
    included: bool
    reason: Optional[str] = Field(None, max_length=200)


class RosterIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    employees: List[RosterItem] = Field(max_length=2000)


@router.put("/periods/{pid}/roster")
def set_roster(pid: str, body: RosterIn, ctx: Ctx = Depends(require("planning.edit"))):
    """Exclure un collaborateur ne concerne QUE ce mois : sa fiche, son historique, ses autres mois et ses shifts passés sont intacts."""
    p = _period(ctx, pid)
    ensure_editable(ctx.db, p.id)
    ended = _contract_ended(ctx, p.start_date)
    rows = {r.employee_id: r for r in ctx.db.scalars(select(m.PeriodEmployee).where(m.PeriodEmployee.period_id == p.id))}
    changed = []
    for it in body.employees:
        e = ctx.db.get(m.Employee, it.employee_id)
        if e is None:
            raise HTTPException(422, "Collaborateur inconnu")
        if it.included and (not e.active or e.id in ended):
            raise HTTPException(422, f"{e.name} n'est pas sélectionnable ({'inactif' if not e.active else 'contrat terminé'}).")
        r = rows.get(e.id)
        if r is None:
            r = m.PeriodEmployee(tenant_id=ctx.tenant_id, period_id=p.id, employee_id=e.id, included=True)
            ctx.db.add(r)
            rows[e.id] = r
        if r.included != it.included or r.reason != it.reason:
            changed.append({"employee": e.name, "included": it.included})
        r.included, r.reason = it.included, it.reason
    ctx.db.flush()
    if changed:
        audit(ctx, "period.roster", "period", p.id, {"changes": changed[:200]})
    items = _roster(ctx, p)
    return {"employees": items, "included": sum(1 for x in items if x["included"]), "total": len(items)}


# ---------- étape 4 : marques, budgets, sites ----------
def _needs(ctx: Ctx, p: m.PlanningPeriod):
    """Besoins du mois SI la marque/le site sont actifs (les bascules du mois sont ignorées pour pouvoir les afficher)."""
    inp = build_input(ctx.db, p, toggles=False)
    by_brand: dict = defaultdict(lambda: {"mandatory_minutes": 0, "optional_minutes": 0, "shifts": 0, "days": set(), "sites": set()})
    by_site: dict = defaultdict(lambda: {"minutes": 0, "shifts": 0, "brands": set()})
    for s in inp.slots:
        for b, mins in s.allocations.items():
            x = by_brand[b]
            x["mandatory_minutes" if s.mandatory else "optional_minutes"] += mins
            x["shifts"] += 1
            x["days"].add(s.day)
            x["sites"].add(s.site)
        by_site[s.site]["minutes"] += s.effective_minutes
        by_site[s.site]["shifts"] += 1
        by_site[s.site]["brands"] |= set(s.allocations)
    return by_brand, by_site


def _budget_check(target: Optional[int], need: dict, strict: bool) -> List[dict]:
    mand, opt = need["mandatory_minutes"], need["optional_minutes"]
    h = lambda x: f"{x / 60:g} h"  # noqa: E731
    out = []
    if target is None:
        if mand + opt:
            out.append({"level": "warning", "text": f"Aucun budget pour ce mois ({h(mand + opt)} de besoins définis). Rien n'est inventé : saisissez-le ou reprenez celui du mois précédent."})
        return out
    if mand + opt == 0 and target:
        out.append({"level": "warning", "text": f"Budget de {h(target)} sans aucun besoin défini (jours et horaires) : ces heures ne pourront pas être planifiées."})
    elif mand > target:
        out.append({"level": "warning" if strict else "info", "text": f"Les besoins obligatoires ({h(mand)}) dépassent le budget ({h(target)}) de {h(mand - target)}"
                    + (" : budget strict, certains shifts resteront non couverts." if strict else " : budget souple, le dépassement sera pénalisé mais possible.")})
    elif target > mand + opt:
        out.append({"level": "info", "text": f"Le budget ({h(target)}) dépasse les heures possibles avec les besoins définis ({h(mand + opt)}) : {h(target - mand - opt)} resteront non planifiées."})
    return out


@router.get("/periods/{pid}/brands")
def period_brands(pid: str, ctx: Ctx = Depends(require("planning.read"))):
    p = _period(ctx, pid)
    first = p.start_date.replace(day=1)
    prev = (first - timedelta(days=1)).replace(day=1)
    toggles = {r.brand_code: r.active for r in ctx.db.scalars(select(m.PeriodBrand).where(m.PeriodBrand.period_id == p.id))}
    budgets = {b.brand_code: b for b in ctx.db.scalars(select(m.MonthlyBudget).where(m.MonthlyBudget.month == first))}
    ref = {b.brand_code: b for b in ctx.db.scalars(select(m.MonthlyBudget).where(m.MonthlyBudget.month == prev))}
    need, _ = _needs(ctx, p)
    sched = brand_schedules(ctx.db)
    sites = {s.code: s.name for s in ctx.db.scalars(select(m.Site))}
    out = []
    for b in ctx.db.scalars(select(m.Brand).order_by(m.Brand.group_code.nulls_last(), m.Brand.name)):
        archived = bool(b.archived_from and b.archived_from <= first)
        n = need.get(b.code, {"mandatory_minutes": 0, "optional_minutes": 0, "shifts": 0, "days": set(), "sites": set()})
        bud = budgets.get(b.code)
        out.append({"code": b.code, "name": b.name, "group_code": b.group_code, "archived": archived,
                    "active": (not archived) and toggles.get(b.code, True),
                    "budget_minutes": bud.target_minutes if bud else None, "strict": bud.strict if bud else True,
                    "reference_minutes": ref[b.code].target_minutes if b.code in ref else None, "reference_month": prev.isoformat(),
                    "need_mandatory_minutes": n["mandatory_minutes"], "need_optional_minutes": n["optional_minutes"], "shifts": n["shifts"],
                    "animation_days": len(n["days"]), "sites": [{"code": c, "name": sites.get(c, c)} for c in sorted(n["sites"])],
                    "schedules": [f"{x['start'][:5]}–{x['end'][:5]}" for x in sched.get(b.code, [])],
                    "checks": _budget_check(bud.target_minutes if bud else None, n, bud.strict if bud else True) if not archived else []})
    return out


class PeriodBrandIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    active: Optional[bool] = None
    budget_minutes: Optional[int] = Field(None, ge=0, le=60 * 10000)
    clear_budget: bool = False
    strict: Optional[bool] = None


@router.put("/periods/{pid}/brands/{code}")
def set_period_brand(pid: str, code: str, body: PeriodBrandIn, ctx: Ctx = Depends(require("budgets.write"))):
    """Activation de la marque et budget horaire POUR CE MOIS (le budget des autres mois n'est jamais modifié)."""
    p = _period(ctx, pid)
    ensure_editable(ctx.db, p.id)
    b = ctx.db.scalar(select(m.Brand).where(m.Brand.code == code))
    if b is None:
        raise HTTPException(404, "Marque inconnue")
    first = p.start_date.replace(day=1)
    detail: dict = {"brand": code, "month": first.isoformat()}
    if body.active is not None:
        r = ctx.db.scalar(select(m.PeriodBrand).where(m.PeriodBrand.period_id == p.id, m.PeriodBrand.brand_code == code))
        if r is None:
            r = m.PeriodBrand(tenant_id=ctx.tenant_id, period_id=p.id, brand_code=code)
            ctx.db.add(r)
        r.active = body.active
        detail["active"] = body.active
    bud = ctx.db.scalar(select(m.MonthlyBudget).where(m.MonthlyBudget.brand_code == code, m.MonthlyBudget.month == first))
    if body.clear_budget and bud is not None:
        detail["budget_before"] = bud.target_minutes
        ctx.db.delete(bud)
        bud = None
    elif body.budget_minutes is not None or body.strict is not None:
        if bud is None:
            if body.budget_minutes is None:
                raise HTTPException(422, "Saisissez d'abord le budget horaire de ce mois.")
            bud = m.MonthlyBudget(tenant_id=ctx.tenant_id, brand_code=code, month=first, target_minutes=body.budget_minutes, strict=True)
            ctx.db.add(bud)
        detail["budget_before"] = bud.target_minutes
        if body.budget_minutes is not None:
            bud.target_minutes = body.budget_minutes
        if body.strict is not None:
            bud.strict = body.strict
        detail["budget_after"], detail["strict"] = bud.target_minutes, bud.strict
    ctx.db.flush()
    audit(ctx, "period.brand", "period", p.id, detail)
    return next(x for x in period_brands(pid, ctx) if x["code"] == code)


@router.get("/periods/{pid}/sites")
def period_sites(pid: str, ctx: Ctx = Depends(require("planning.read"))):
    p = _period(ctx, pid)
    first = p.start_date.replace(day=1)
    toggles = {r.site_code: r.active for r in ctx.db.scalars(select(m.PeriodSite).where(m.PeriodSite.period_id == p.id))}
    _, need = _needs(ctx, p)
    brands = {b.code: b.name for b in ctx.db.scalars(select(m.Brand))}
    out = []
    for s in ctx.db.scalars(select(m.Site).order_by(m.Site.name)):
        archived = bool(s.archived_from and s.archived_from <= first)
        n = need.get(s.code, {"minutes": 0, "shifts": 0, "brands": set()})
        out.append({"code": s.code, "name": s.name, "archived": archived, "active": (not archived) and toggles.get(s.code, True),
                    "shifts": n["shifts"], "minutes": n["minutes"], "brands": [{"code": c, "name": brands.get(c, c)} for c in sorted(n["brands"])]})
    return out


class PeriodSiteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    active: bool


@router.put("/periods/{pid}/sites/{code}")
def set_period_site(pid: str, code: str, body: PeriodSiteIn, ctx: Ctx = Depends(require("planning.edit"))):
    p = _period(ctx, pid)
    ensure_editable(ctx.db, p.id)
    if ctx.db.scalar(select(m.Site).where(m.Site.code == code)) is None:
        raise HTTPException(404, "Site inconnu")
    r = ctx.db.scalar(select(m.PeriodSite).where(m.PeriodSite.period_id == p.id, m.PeriodSite.site_code == code))
    if r is None:
        r = m.PeriodSite(tenant_id=ctx.tenant_id, period_id=p.id, site_code=code)
        ctx.db.add(r)
    r.active = body.active
    ctx.db.flush()
    audit(ctx, "period.site", "period", p.id, {"site": code, "active": body.active})
    return next(x for x in period_sites(pid, ctx) if x["code"] == code)


# ---------- étape 5 : vérification avant génération ----------
@router.get("/periods/{pid}/readiness")
def readiness(pid: str, ctx: Ctx = Depends(require("planning.read"))):
    """Récapitulatif et incohérences AVANT génération (lecture seule)."""
    p = _period(ctx, pid)
    first, last = month_bounds(p.start_date.year, p.start_date.month)
    inp = build_input(ctx.db, p)
    ros = _roster(ctx, p)
    brands = period_brands(pid, ctx)
    sites = period_sites(pid, ctx)
    issues: List[dict] = []
    included = [e for e in inp.employees if not e.excluded]
    if not included:
        issues.append({"level": "blocking", "text": "Aucun collaborateur retenu pour ce mois."})
    active_brands = [b for b in brands if b["active"]]
    for b in active_brands:
        issues += [{**c, "text": f"{b['name']} : {c['text']}"} for c in b["checks"]]
        if b["shifts"] and not any(b["code"] in e.brands for e in included):
            issues.append({"level": "warning", "text": f"{b['name']} : aucun collaborateur retenu n'est autorisé sur cette marque."})
    for e in included:
        if not any(x["code"] in e.brands for x in active_brands):
            issues.append({"level": "warning", "text": f"{e.name} n'est autorisé·e sur aucune marque active ce mois-ci."})
    days = [first + timedelta(days=i) for i in range((last - first).days + 1)]
    unavail = {e.name: sum(1 for d in days if e.blocked(d)) for e in included}
    sundays = [d for d in days if d.weekday() == 6]
    reserved = sum(min(e.sunday_quota, len(sundays)) for e in included if e.sunday_quota is not None)
    sun_total = sum(1 for s in inp.slots if s.day.weekday() == 6)
    if reserved > sun_total and sun_total:
        issues.append({"level": "warning", "text": f"{reserved} dimanches réservés pour {sun_total} shifts du dimanche : certains quotas ne pourront pas être atteints."})
    excl_codes = {e.id for e in inp.employees if e.excluded}
    if excl_codes:
        locked = [a for a in assignments_for_validation(ctx.db, inp, p) if a.locked and a.employee_id in excl_codes]
        if locked:
            issues.append({"level": "blocking", "text": f"{len(locked)} affectation(s) verrouillée(s) appartiennent à des collaborateurs exclus du mois : déverrouillez-les ou réintégrez ces collaborateurs."})
    keys = {s.id for s in inp.slots}
    orphan = ctx.db.scalar(select(func.count()).select_from(m.Assignment).join(m.Shift, m.Shift.id == m.Assignment.shift_id)
                           .where(m.Assignment.period_id == p.id, m.Shift.slot_key.not_like("MANUAL|%"), m.Shift.slot_key.not_in(keys or {""})))
    if orphan:
        issues.append({"level": "warning", "text": f"{orphan} affectation(s) existante(s) portent sur une marque ou un site désactivé ce mois : une nouvelle génération les retirera."})
    overrides = ctx.db.scalars(select(m.EmployeeMonthParams).where(m.EmployeeMonthParams.month == first)).all()
    st = statuses(ctx.db, [p])[p.id]
    return {"period": {**serialize(p), **st}, "days": len(days), "sundays": len(sundays), "saturdays": sum(1 for d in days if d.weekday() == 5),
            "employees": {"included": len(included), "excluded": [x["name"] for x in ros if x["state"] == "excluded"],
                          "contract_ended": [x["name"] for x in ros if x["state"] == "contract_ended"], "inactive": [x["name"] for x in ros if x["state"] == "inactive"]},
            "brands": {"active": [b["name"] for b in active_brands], "inactive": [b["name"] for b in brands if not b["active"]]},
            "sites": {"active": [s["name"] for s in sites if s["active"]], "inactive": [s["name"] for s in sites if not s["active"]]},
            "budget_minutes": sum(b["budget_minutes"] or 0 for b in active_brands), "shifts": len(inp.slots), "mandatory_shifts": sum(1 for s in inp.slots if s.mandatory),
            "effective_minutes": sum(s.effective_minutes for s in inp.slots), "sunday_shifts": sun_total, "sundays_reserved": reserved,
            "unavailabilities": {k: v for k, v in sorted(unavail.items()) if v}, "unavailable_days": sum(unavail.values()),
            "constraints": {"max_days_exceptions": sum(1 for o in overrides if o.max_days_set), "sunday_quotas": sum(1 for e in included if e.sunday_quota is not None),
                            "strict_time_prefs": sum(1 for e in included if e.time_pref and e.time_pref_strict),
                            "max_days": sum(1 for e in included if e.max_days_count is not None)},
            "issues": issues, "ready": not any(i["level"] == "blocking" for i in issues)}


@router.get("/employees/{eid}/impact")
def employee_impact(eid: str, ctx: Ctx = Depends(require("planning.read"))):
    """Après la modification d'un paramètre PERMANENT : plannings déjà créés devenus incompatibles pour ce collaborateur.
    Rien n'est modifié : l'utilisateur choisit d'ouvrir le planning, de corriger à la main ou de réoptimiser."""
    from planning_solver.compat import compatibility
    e = get_or_404(ctx, m.Employee, eid)
    rows = list(ctx.db.scalars(select(m.PlanningPeriod).where(m.PlanningPeriod.archived_at.is_(None)).order_by(m.PlanningPeriod.start_date)))
    st = statuses(ctx.db, rows)
    out = []
    for p in rows:
        if not st[p.id]["assignments"]:
            continue
        inp = build_input(ctx.db, p)
        res = compatibility(inp, assignments_for_validation(ctx.db, inp, p))
        hard = [h for h in res["hard"] if e.name in h]
        soft = [s for s in res["soft"] if s.get("employee") == e.name]
        if hard or soft:
            out.append({"period_id": str(p.id), "name": p.name, "status": st[p.id]["status"], "hard": len(hard), "soft": len(soft)})
    return {"employee": e.name, "periods": out}
