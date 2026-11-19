"""Plusieurs mois / plusieurs années : période d'un mois, calendrier et besoins calculés, paramètres propres à un mois, révision."""
import calendar as _cal
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from planning_solver.sundays import sunday_summary

from .. import models as m
from ..deps import Ctx, audit, get_or_404, require
from ..services_bridge import assignments_for_validation, build_input
from .crud import serialize

router = APIRouter(tags=["mois et années"])

MONTHS_FR = ["Janvier", "Février", "Mars", "Avril", "Mai", "Juin", "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre"]
DAYS_FR = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]


def month_bounds(year: int, month: int) -> tuple:
    return date(year, month, 1), date(year, month, _cal.monthrange(year, month)[1])


def parse_month(s: str) -> date:
    try:
        y, mo = s.split("-")
        return date(int(y), int(mo), 1)
    except (ValueError, TypeError):
        raise HTTPException(422, "Mois invalide (attendu : AAAA-MM)")


def find_period(ctx: Ctx, first: date, last: date) -> Optional[m.PlanningPeriod]:
    return ctx.db.scalar(select(m.PlanningPeriod).where(m.PlanningPeriod.deleted_at.is_(None), m.PlanningPeriod.start_date == first, m.PlanningPeriod.end_date == last)
                         .order_by(m.PlanningPeriod.created_at))


class MonthIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    year: int = Field(ge=2000, le=2100)
    month: int = Field(ge=1, le=12)


@router.post("/periods/ensure")
def ensure_period(body: MonthIn, ctx: Ctx = Depends(require("planning.edit"))):
    """Ouvre le planning du mois (le crée s'il n'existe pas). Ne touche jamais aux autres mois ni aux affectations existantes."""
    first, last = month_bounds(body.year, body.month)
    p = find_period(ctx, first, last)
    created = p is None
    if created:
        p = m.PlanningPeriod(tenant_id=ctx.tenant_id, name=f"{MONTHS_FR[body.month - 1]} {body.year}", start_date=first, end_date=last)
        ctx.db.add(p)
        ctx.db.flush()
        audit(ctx, "period.create", "period", p.id, {"month": first.isoformat()})
    from ..budgets import init_budgets_from_base
    init_budgets_from_base(ctx.db, ctx.tenant_id, p, ctx.user.id)  # nouveau mois : budgets de base préremplis (jamais un ajustement écrasé)
    return {**serialize(p), "created": created}


@router.get("/calendar")
def month_calendar(year: int = Query(ge=2000, le=2100), month: int = Query(ge=1, le=12), ctx: Ctx = Depends(require("planning.read"))):
    """Calendrier et besoins du mois, calculés à partir des besoins réellement configurés (aucune valeur propre à un mois précis)."""
    first, last = month_bounds(year, month)
    p = find_period(ctx, first, last)
    shell = p or m.PlanningPeriod(id=uuid.uuid4(), name="", start_date=first, end_date=last)
    inp = build_input(ctx.db, shell)
    n_days = (last - first).days + 1
    all_days = [first + timedelta(days=i) for i in range(n_days)]
    wd = {DAYS_FR[i]: sum(1 for d in all_days if d.weekday() == i) for i in range(7)}
    sundays = [d for d in all_days if d.weekday() == 6]
    by_brand: dict = {}
    for s in inp.slots:
        for b in s.allocations:
            row = by_brand.setdefault(b, {"days": set(), "shifts": 0})
            row["days"].add(s.day)
            row["shifts"] += 1
    sun_slots = [s for s in inp.slots if s.day.weekday() == 6]
    per_site: dict = {}
    for s in sun_slots:
        per_site[s.site] = per_site.get(s.site, 0) + 1
    assigns = assignments_for_validation(ctx.db, inp, p) if p else []
    summary = sunday_summary(inp, assigns)
    n_assign = ctx.db.scalar(select(func.count()).select_from(m.Assignment).where(m.Assignment.period_id == p.id)) if p else 0
    budgets_defined = ctx.db.scalar(select(func.count()).select_from(m.MonthlyBudget).where(m.MonthlyBudget.month == first)) or 0
    return {"year": year, "month": month, "label": f"{MONTHS_FR[month - 1]} {year}", "start": first.isoformat(), "end": last.isoformat(),
            "days": n_days, "weekdays": wd, "saturdays": wd["Samedi"], "sundays": len(sundays), "sunday_dates": [d.isoformat() for d in sundays],
            "shifts_total": len(inp.slots), "mandatory_shifts": sum(1 for s in inp.slots if s.mandatory),
            "effective_hours": round(sum(s.effective_minutes for s in inp.slots) / 60, 2),
            "sunday_shifts_total": summary["total"], "sunday_shifts_per_site": per_site,
            "brands": [{"brand": b, "open_days": len(v["days"]), "shifts": v["shifts"]} for b, v in sorted(by_brand.items())],
            "budgets": [{"brand": b.brand, "target_minutes": b.target_minutes} for b in inp.budgets], "budgets_missing": budgets_defined == 0,
            "period_id": str(p.id) if p else None, "has_period": p is not None, "assignments": n_assign, "has_plan": n_assign > 0,
            "sunday": summary}


class MonthParamsIn(BaseModel):
    """Mise à jour PARTIELLE : seuls les champs envoyés changent (dimanches et exception de jours maximum sont indépendants)."""
    model_config = ConfigDict(extra="forbid")
    sunday_quota: Optional[int] = Field(None, ge=0, le=5)
    sunday_mode: Literal["max", "exact"] = "exact"
    max_days_set: Optional[bool] = None  # True = exception pour ce mois ; False = valeur habituelle de la fiche
    max_days_count: Optional[int] = Field(None, ge=1, le=31)
    max_days_period: Optional[Literal["week", "month"]] = None
    days_set: Optional[bool] = None  # True = exception du mois sur les jours minimum / maximum ; False = valeurs habituelles de la fiche
    min_days: Optional[int] = Field(None, ge=1, le=31)  # None = pas de préférence
    max_days: Optional[int] = Field(None, ge=1, le=31)


@router.get("/month-params")
def month_params(month: str, ctx: Ctx = Depends(require("employees.read"))):
    """Paramètres propres au mois pour chaque collaborateur (quota de dimanches). `source` : month = saisi pour ce mois ;
    default = valeur historique de la fiche (aucune valeur saisie pour ce mois) ; none = aucun quota."""
    first = parse_month(month)
    rows = {r.employee_id: r for r in ctx.db.scalars(select(m.EmployeeMonthParams).where(m.EmployeeMonthParams.month == first))}
    return [_mp_view(e, rows.get(e.id)) for e in ctx.db.scalars(select(m.Employee).where(m.Employee.deleted_at.is_(None)).order_by(m.Employee.code))]


def _effective(ctx: Ctx, e: m.Employee, months) -> dict:
    rows = {r.month: r for r in ctx.db.scalars(select(m.EmployeeMonthParams).where(m.EmployeeMonthParams.employee_id == e.id))}
    legacy = (e.sunday_quota, e.sunday_mode or "max") if e.sunday_quota_migrated_at is None else (None, "max")
    return {mo: ((rows[mo].sunday_quota, rows[mo].sunday_mode) if mo in rows else legacy) for mo in months}


def migrate_legacy_quota(ctx: Ctx, e: m.Employee, exclude: Optional[date] = None) -> Optional[dict]:
    """Report SÉCURISÉ du quota historique (valeur unique de la fiche) vers les mois déjà planifiés, une seule fois par collaborateur :
    - seuls les mois sans valeur mensuelle reçoivent une copie exacte (quota ET mode) : leur valeur effective ne change pas ;
    - les valeurs mensuelles existantes, les affectations et les versions publiées ne sont jamais modifiées ;
    - la valeur historique est conservée en base (jamais effacée) ; un marqueur indique qu'elle ne sert plus de défaut ;
    - contrôle avant/après : si la valeur effective d'un mois planifié changeait, la transaction est annulée ;
    - tracé dans le journal d'audit (mois copiés, mois déjà renseignés, mois publiés)."""
    if e.sunday_quota is None or e.sunday_quota_migrated_at is not None:
        return None
    periods = list(ctx.db.scalars(select(m.PlanningPeriod).where(m.PlanningPeriod.deleted_at.is_(None))))
    months = sorted({pd.start_date.replace(day=1) for pd in periods})
    keep = [mo for mo in months if mo != exclude]
    before = _effective(ctx, e, keep)
    have = {r.month for r in ctx.db.scalars(select(m.EmployeeMonthParams).where(m.EmployeeMonthParams.employee_id == e.id))}
    copied = [mo for mo in keep if mo not in have]
    for mo in copied:
        ctx.db.add(m.EmployeeMonthParams(tenant_id=ctx.tenant_id, employee_id=e.id, month=mo, sunday_quota=e.sunday_quota, sunday_mode=e.sunday_mode or "max"))
    e.sunday_quota_migrated_at = datetime.now(timezone.utc)
    ctx.db.flush()
    after = _effective(ctx, e, keep)
    if after != before:
        raise HTTPException(500, "Report des quotas interrompu : une valeur existante aurait changé. Aucune modification enregistrée.")
    published = sorted({pd.start_date.replace(day=1).isoformat() for pd in periods for v in ctx.db.scalars(
        select(m.ScheduleVersion).where(m.ScheduleVersion.period_id == pd.id, m.ScheduleVersion.published.is_(True)))})
    report = {"legacy": {"sunday_quota": e.sunday_quota, "sunday_mode": e.sunday_mode}, "months_copied": [x.isoformat() for x in copied],
              "months_already_set": [x.isoformat() for x in keep if x in have], "published_months": published}
    audit(ctx, "employee.sunday_quota_migration", "employee", e.id, report)
    return report


@router.put("/employees/{eid}/month-params/{month}")
def set_month_params(eid: str, month: str, body: MonthParamsIn, ctx: Ctx = Depends(require("employees.write"))):
    """Enregistre les paramètres d'UN mois (quota de dimanches, exception de jours maximum) ; les autres mois ne sont jamais modifiés."""
    e = get_or_404(ctx, m.Employee, eid)
    first = parse_month(month)
    fs = body.model_fields_set
    n_days = _cal.monthrange(first.year, first.month)[1]
    n_sun = sum(1 for i in range(n_days) if (first + timedelta(days=i)).weekday() == 6)
    sunday = bool(fs & {"sunday_quota", "sunday_mode"})
    if sunday:
        if body.sunday_quota is not None and body.sunday_quota > n_sun:
            raise HTTPException(422, f"{MONTHS_FR[first.month - 1]} {first.year} ne compte que {n_sun} dimanche(s).")
        if body.sunday_mode == "exact" and body.sunday_quota is None:
            raise HTTPException(422, "Un objectif exact exige un nombre de dimanches.")
    if body.max_days_set:
        if (body.max_days_count is None) != (body.max_days_period is None):
            raise HTTPException(422, "Nombre de jours et période vont ensemble (ou « Pas de préférence » dans les deux).")
        if body.max_days_period == "week" and body.max_days_count > 7:
            raise HTTPException(422, "Une semaine compte au plus 7 jours.")
        if body.max_days_period == "month" and body.max_days_count > n_days:
            raise HTTPException(422, f"{MONTHS_FR[first.month - 1]} {first.year} compte {n_days} jours.")
    if body.days_set:
        from ..limits import days_settings_error
        err = days_settings_error(ctx.db, ctx.tenant_id, e.brands or {}, body.min_days, body.max_days, n_days, f"{MONTHS_FR[first.month - 1]} {first.year}")
        if err:
            raise HTTPException(422, err)
    legacy = (e.sunday_quota, e.sunday_mode or "max") if e.sunday_quota is not None and e.sunday_quota_migrated_at is None else (None, "max")
    migrate_legacy_quota(ctx, e, exclude=first)
    row = ctx.db.scalar(select(m.EmployeeMonthParams).where(m.EmployeeMonthParams.employee_id == e.id, m.EmployeeMonthParams.month == first))
    before = None if row is None else {"sunday_quota": row.sunday_quota, "sunday_mode": row.sunday_mode, "max_days_set": row.max_days_set,
                                       "max_days_count": row.max_days_count, "max_days_period": row.max_days_period,
                                       "days_set": row.days_set, "min_days": row.min_days, "max_days": row.max_days}
    if row is None:  # nouvelle ligne : le quota de dimanches en vigueur pour ce mois est repris tel quel (rien ne change en silence)
        row = m.EmployeeMonthParams(tenant_id=ctx.tenant_id, employee_id=e.id, month=first, sunday_quota=legacy[0], sunday_mode=legacy[1])
        ctx.db.add(row)
    if sunday:
        row.sunday_quota, row.sunday_mode = body.sunday_quota, body.sunday_mode
    if "max_days_set" in fs:
        row.max_days_set = bool(body.max_days_set)
        row.max_days_count, row.max_days_period = (body.max_days_count, body.max_days_period) if body.max_days_set else (None, None)
    if "days_set" in fs:
        row.days_set = bool(body.days_set)
        row.min_days, row.max_days = (body.min_days, body.max_days) if body.days_set else (None, None)
    ctx.db.flush()
    audit(ctx, "employee.month_params", "employee", e.id, {"month": first.isoformat(), "before": before, "after": body.model_dump(include=fs)})
    published = ctx.db.scalar(select(func.count()).select_from(m.ScheduleVersion).join(m.PlanningPeriod, m.PlanningPeriod.id == m.ScheduleVersion.period_id)
                              .where(m.ScheduleVersion.published.is_(True), m.PlanningPeriod.start_date == first)) or 0
    return {**_mp_view(e, row), "month": first.isoformat(), "published": published > 0,
            "notice": "Ce mois a une version publiée : elle reste inchangée ; le nouveau réglage s'appliquera à la prochaine génération." if published else None}


def _mp_view(e: m.Employee, r: Optional[m.EmployeeMonthParams]) -> dict:
    if r is not None:
        sq = {"sunday_quota": r.sunday_quota, "sunday_mode": r.sunday_mode, "source": "month"}
    elif e.sunday_quota is not None and e.sunday_quota_migrated_at is None:
        sq = {"sunday_quota": e.sunday_quota, "sunday_mode": e.sunday_mode or "max", "source": "default"}
    else:
        sq = {"sunday_quota": None, "sunday_mode": "max", "source": "none"}
    exc = r is not None and r.max_days_set
    return {"employee_id": str(e.id), **sq, "max_days_set": exc,
            "max_days_count": r.max_days_count if exc else e.max_days_count, "max_days_period": r.max_days_period if exc else e.max_days_period,
            "usual_max_days_count": e.max_days_count, "usual_max_days_period": e.max_days_period,
            "days_set": bool(r is not None and r.days_set), "min_days": r.min_days if r is not None and r.days_set else e.min_days_month,
            "max_days": r.max_days if r is not None and r.days_set else e.max_days_month,
            "usual_min_days": e.min_days_month, "usual_max_days": e.max_days_month}


@router.get("/revision")
def revision(ctx: Ctx = Depends(require("self.read"))):
    """Empreinte légère de l'état partagé (journal d'audit append-only) : les clients la comparent pour se resynchroniser
    quand un autre manager modifie le planning, sans rechargement manuel."""
    n, last = ctx.db.execute(select(func.count(), func.max(m.AuditLog.created_at)).select_from(m.AuditLog)).one()
    return {"revision": f"{n}:{last.isoformat() if last else ''}"}
