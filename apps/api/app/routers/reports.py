"""Pilotage : tableau de bord, heures et rentabilité par client / marque / mission / site, exports paie et facturation.
Tout est recalculé à partir des shifts, imputations et heures saisies. Un coût ou un tarif non renseigné reste « non renseigné » :
aucun montant n'est supposé, et une marge n'est calculée que sur les heures dont le coût ET le tarif sont connus."""
import csv
import io
from collections import defaultdict
from datetime import date, timedelta
from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import select

from planning_solver.metrics import plan_metrics

from planning_solver.validator import validate

from .. import models as m
from ..deps import Ctx, get_or_404, require
from ..rbac import has_permission
from ..services_bridge import assignments_for_validation, build_input
from .exports import _job, _safe
from .months import parse_month
from .planning import scope_brands

router = APIRouter(tags=["pilotage"])


def _req_code(slot_key: str) -> str:
    return slot_key.split("|")[0].split("#")[0]


def _new_line(key: str, name: str, **extra) -> dict:
    return {"key": key, "name": name, "requested_minutes": None, "planned_minutes": 0, "actual_minutes": 0, "validated_minutes": 0, "overtime_minutes": 0, "absent_minutes": 0,
            "_cost_planned": 0, "_cost_actual": 0, "_bill_planned": 0, "_bill_actual": 0, "_margin_planned": 0, "_margin_actual": 0, "cost_missing_minutes": 0, "bill_missing_minutes": 0, **extra}


def _finish(line: dict, see_money: bool) -> dict:
    out = {k: v for k, v in line.items() if not k.startswith("_")}
    out["remaining_minutes"] = line["requested_minutes"] - line["planned_minutes"] if line["requested_minutes"] is not None else None
    known_cost = line["planned_minutes"] > line["cost_missing_minutes"]
    known_bill = line["planned_minutes"] > line["bill_missing_minutes"]
    if see_money:
        out.update(cost_planned_cents=round(line["_cost_planned"] / 60) if known_cost else None, cost_actual_cents=round(line["_cost_actual"] / 60) if known_cost else None,
                   billable_planned_cents=round(line["_bill_planned"] / 60) if known_bill else None, billable_actual_cents=round(line["_bill_actual"] / 60) if known_bill else None,
                   margin_planned_cents=round(line["_margin_planned"] / 60) if known_cost and known_bill else None, margin_actual_cents=round(line["_margin_actual"] / 60) if known_cost and known_bill else None,
                   complete=line["cost_missing_minutes"] == 0 and line["bill_missing_minutes"] == 0)
    else:
        out.update(cost_planned_cents=None, cost_actual_cents=None, margin_planned_cents=None, margin_actual_cents=None, billable_planned_cents=None, billable_actual_cents=None, complete=False)
        out["cost_missing_minutes"] = out["bill_missing_minutes"] = 0
    return out


def finance_report(ctx: Ctx, first: date, see_money: bool, scope: Optional[set] = None) -> dict:
    last = (first.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    db = ctx.db
    clients = {c.id: c for c in db.scalars(select(m.Client))}
    brands = {b.code: b for b in db.scalars(select(m.Brand))}
    sites = {s.code: s.name for s in db.scalars(select(m.Site))}
    missions = {x.code: x for x in db.scalars(select(m.Mission))}
    req_mission = {r.code: r.mission_id for r in db.scalars(select(m.StaffingRequirement).where(m.StaffingRequirement.mission_id.is_not(None)))}
    missions_by_id = {x.id: x for x in missions.values()}
    contracts: Dict = defaultdict(list)
    for c in db.scalars(select(m.EmploymentContract)):
        contracts[c.employee_id].append(c)

    def hourly(emp_id, day):
        for c in contracts.get(emp_id, []):
            if (c.start_date is None or c.start_date <= day) and (c.end_date is None or c.end_date >= day) and c.hourly_cost_cents is not None:
                return c.hourly_cost_cents
        return None

    def rate(mission, brand_code):
        if mission is not None and mission.billing_rate_cents is not None:
            return mission.billing_rate_cents
        b = brands.get(brand_code)
        if b is not None and b.billing_rate_cents is not None:
            return b.billing_rate_cents
        owner = clients.get(mission.client_id) if mission is not None else (clients.get(b.client_id) if b is not None else None)
        return owner.billing_rate_cents if owner is not None else None

    groups: Dict[str, Dict[str, dict]] = {"client": {}, "brand": {}, "mission": {}, "site": {}}

    def line(kind, key, name, **extra):
        return groups[kind].setdefault(key, _new_line(key, name, **extra))

    rows = db.execute(select(m.Assignment, m.Shift).join(m.Shift, m.Shift.id == m.Assignment.shift_id).where(m.Shift.day >= first, m.Shift.day <= last)).all()
    ids = [a.id for a, _ in rows]
    allocs: Dict = defaultdict(dict)
    if ids:
        for r in db.scalars(select(m.BrandAllocation).where(m.BrandAllocation.assignment_id.in_(ids))):
            allocs[r.assignment_id][r.brand_code] = r.minutes
    entries = {(t.shift_id, t.employee_id): t for t in db.scalars(select(m.TimeEntry).where(m.TimeEntry.day >= first, m.TimeEntry.day <= last))}
    for a, s in rows:
        t = entries.get((s.id, a.employee_id))
        mission = missions_by_id.get(req_mission.get(_req_code(s.slot_key)))
        for brand, minutes in allocs[a.id].items():
            if scope is not None and brand not in scope:
                continue
            b = brands.get(brand)
            client_id = mission.client_id if mission is not None else (b.client_id if b is not None else None)
            client = clients.get(client_id)
            cost, bill = hourly(a.employee_id, s.day), rate(mission, brand)
            share = s.effective_minutes and minutes / s.effective_minutes
            worked = round(t.worked_minutes * share) if t is not None else 0
            over = round(t.overtime_minutes * share) if t is not None else 0
            targets = [line("brand", brand, b.name if b else brand, client=client.name if client else None), line("site", s.site_code, sites.get(s.site_code, s.site_code)),
                       line("client", str(client.id) if client else "none", client.name if client else "Sans client")]
            if mission is not None:
                targets.append(line("mission", mission.code, mission.title, client=client.name if client else None, brand=brand, status=mission.status))
            for L in targets:
                L["planned_minutes"] += minutes
                L["actual_minutes"] += worked
                L["overtime_minutes"] += over
                if t is not None and t.validated_at is not None:
                    L["validated_minutes"] += worked
                if t is not None and t.status == "absent":
                    L["absent_minutes"] += minutes
                if cost is None:
                    L["cost_missing_minutes"] += minutes
                else:
                    L["_cost_planned"] += minutes * cost
                    L["_cost_actual"] += worked * cost
                if bill is None:
                    L["bill_missing_minutes"] += minutes
                else:
                    L["_bill_planned"] += minutes * bill
                    L["_bill_actual"] += worked * bill
                if cost is not None and bill is not None:
                    L["_margin_planned"] += minutes * (bill - cost)
                    L["_margin_actual"] += worked * (bill - cost)
    # heures demandées : budget mensuel de la marque ; heures commandées de la mission (sur toute la mission)
    for bud in db.scalars(select(m.MonthlyBudget).where(m.MonthlyBudget.month == first)):
        if scope is not None and bud.brand_code not in scope:
            continue
        b = brands.get(bud.brand_code)
        client = clients.get(b.client_id) if b is not None else None
        L = line("brand", bud.brand_code, b.name if b else bud.brand_code, client=client.name if client else None)
        L["requested_minutes"] = (L["requested_minutes"] or 0) + bud.target_minutes
        C = line("client", str(client.id) if client else "none", client.name if client else "Sans client")
        C["requested_minutes"] = (C["requested_minutes"] or 0) + bud.target_minutes
    for x in missions.values():
        if x.code in groups["mission"]:
            groups["mission"][x.code]["requested_minutes"] = x.budget_minutes
    return {"month": first.isoformat(), "currency": "CHF", "see_money": see_money,
            **{f"by_{k}": sorted((_finish(L, see_money) for L in g.values()), key=lambda r: r["name"]) for k, g in groups.items()}}


@router.get("/reports/finance")
def finance(month: str, ctx: Ctx = Depends(require("reports.read"))):
    return finance_report(ctx, parse_month(month), has_permission(ctx.user.role, "finance.read"), scope_brands(ctx))


@router.get("/periods/{pid}/dashboard")
def dashboard(pid: str, day: Optional[date] = None, ctx: Ctx = Depends(require("planning.read"))):
    """Vue de pilotage du mois : collaborateurs, couverture, remplacements en attente, équité, marques et sites, finances si autorisé."""
    p = get_or_404(ctx, m.PlanningPeriod, pid)
    inp = build_input(ctx.db, p)
    base = assignments_for_validation(ctx.db, inp, p)
    mx = plan_metrics(inp, base)
    today = day or date.today()
    ref_day = today if p.start_date <= today <= p.end_date else p.start_date
    active = [e for e in inp.employees if not e.excluded]
    unavailable = [e for e in active if e.blocked(ref_day)]
    working = {a.employee_id for a in base if a.day == ref_day}
    planned = {a.employee_id for a in base}
    rows = [r for r in mx["employees"] if not r["excluded"]]
    under = [r for r in rows if r["target_minutes"] and r["attainment"] is not None and r["attainment"] < 90]
    near = []
    weeks: Dict = defaultdict(lambda: defaultdict(int))
    for a in base:
        weeks[a.employee_id][a.day.isocalendar()[:2]] += a.effective_minutes
    for e in active:
        c = e.contract
        limit = min([v for v in (c.weekly_max_minutes if c else None, e.legal_weekly_max_minutes) if v is not None], default=None)
        peak = max(weeks[e.id].values(), default=0)
        if limit and peak >= 0.9 * limit:
            near.append({"name": e.name, "detail": f"{peak / 60:g} h sur une semaine pour un maximum de {limit / 60:g} h"})
        if c and c.monthly_max_minutes:
            tot = sum(weeks[e.id].values())
            if tot >= 0.9 * c.monthly_max_minutes:
                near.append({"name": e.name, "detail": f"{tot / 60:g} h sur le mois pour un maximum de {c.monthly_max_minutes / 60:g} h"})
    hard = validate(inp, base)
    pending = [v for v in hard if v.startswith(("UNAVAILABLE", "EXCLUDED_FROM_PERIOD", "REST_WEEKDAY"))]  # titulaire qui ne peut plus assurer son shift
    budgets = []
    planned_by_brand = mx["by_brand"]
    for bud in ctx.db.scalars(select(m.MonthlyBudget).where(m.MonthlyBudget.month == p.start_date.replace(day=1))):
        budgets.append({"brand": bud.brand_code, "target_minutes": bud.target_minutes, "planned_minutes": planned_by_brand.get(bud.brand_code, 0), "remaining_minutes": bud.target_minutes - planned_by_brand.get(bud.brand_code, 0), "strict": bud.strict})
    site_names = {s.code: s.name for s in ctx.db.scalars(select(m.Site))}
    see_money = has_permission(ctx.user.role, "finance.read")
    fin = finance_report(ctx, p.start_date.replace(day=1), see_money) if has_permission(ctx.user.role, "reports.read") else None
    totals = None
    if fin:
        lines = fin["by_brand"]
        totals = {"planned_minutes": sum(x["planned_minutes"] for x in lines), "actual_minutes": sum(x["actual_minutes"] for x in lines), "validated_minutes": sum(x["validated_minutes"] for x in lines)}
        if see_money:
            totals.update({k: (sum(x[k] for x in lines if x[k] is not None) if any(x[k] is not None for x in lines) else None) for k in ("cost_planned_cents", "cost_actual_cents", "billable_planned_cents", "margin_planned_cents")})
            totals["complete"] = all(x["complete"] for x in lines) if lines else False
    return {"period": {"id": str(p.id), "name": p.name}, "reference_day": ref_day.isoformat(),
            "people": {"active": len(active), "planned": len(planned), "working_today": len(working), "available_today": len([e for e in active if not e.blocked(ref_day) and e.id not in working]),
                       "unavailable_today": len(unavailable), "unavailable_names": [e.name for e in unavailable][:30], "under_target": sorted(under, key=lambda r: r["attainment"])[:30], "near_limits": near[:30]},
            "planning": {"shifts": mx["assignments"] + mx["uncovered_shifts"], "mandatory": mx["mandatory_shifts"], "covered": mx["covered_shifts"], "uncovered": mx["uncovered_shifts"], "uncovered_minutes": mx["uncovered_minutes"],
                         "coverage_rate": mx["coverage_rate"], "pending_replacements": len(pending), "hard_violations": len(hard), "soft_unsatisfied": mx["soft_unsatisfied"], "soft_detail": mx["soft_detail"]},
            "brands": sorted(({"code": k, "minutes": v} for k, v in mx["by_brand"].items()), key=lambda r: -r["minutes"]), "budgets": budgets,
            "sites": sorted(({"code": k, "name": site_names.get(k, k), "minutes": v} for k, v in mx["by_site"].items()), key=lambda r: -r["minutes"]),
            "equity": {"employees": rows, "gap_to_targets_minutes": mx["gap_to_targets_minutes"], "sundays_min": mx["sundays_min"], "sundays_max": mx["sundays_max"], "max_consecutive": mx["max_consecutive"]},
            "finance": totals, "objective": mx["objective"]}


def _csv(name: str, head: list, rows: list) -> Response:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(head)
    for r in rows:
        w.writerow([_safe(x) for x in r])
    return Response(buf.getvalue(), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{name}"'})


def _money(c: Optional[int]) -> str:
    return "" if c is None else f"{c / 100:.2f}"


@router.get("/reports/payroll.csv")
def payroll_csv(month: str = Query(...), ctx: Ctx = Depends(require("export.run"))):
    """Données pour la paie : heures planifiées et réelles par collaborateur, heures validées uniquement comptées comme définitives."""
    first = parse_month(month)
    last = (first.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    emps = {e.id: e for e in ctx.db.scalars(select(m.Employee))}
    see_money = has_permission(ctx.user.role, "finance.read")
    costs: Dict = {}
    for c in ctx.db.scalars(select(m.EmploymentContract)):
        if c.hourly_cost_cents is not None and (c.start_date is None or c.start_date <= last) and (c.end_date is None or c.end_date >= first):
            costs[c.employee_id] = c.hourly_cost_cents
    by: Dict = defaultdict(lambda: {"planned": 0, "worked": 0, "validated": 0, "overtime": 0, "late": 0, "absent": 0, "sundays": 0})
    for a, s in ctx.db.execute(select(m.Assignment, m.Shift).join(m.Shift, m.Shift.id == m.Assignment.shift_id).where(m.Shift.day >= first, m.Shift.day <= last)).all():
        by[a.employee_id]["planned"] += s.effective_minutes
        by[a.employee_id]["sundays"] += 1 if s.day.weekday() == 6 else 0
    for t in ctx.db.scalars(select(m.TimeEntry).where(m.TimeEntry.day >= first, m.TimeEntry.day <= last)):
        r = by[t.employee_id]
        r["worked"] += t.worked_minutes
        r["overtime"] += t.overtime_minutes
        r["late"] += t.late_minutes
        r["absent"] += 1 if t.status == "absent" else 0
        r["validated"] += t.worked_minutes if t.validated_at else 0
    rows = [[e.code, e.name, r["planned"] / 60, r["worked"] / 60, r["validated"] / 60, r["overtime"] / 60, r["late"], r["absent"], r["sundays"]] +
            ([_money(costs.get(eid))] if see_money else []) for eid, r in by.items() for e in [emps[eid]]]
    _job(ctx, "payroll_csv", {"month": month})
    head = ["Code", "Collaborateur", "Heures planifiées", "Heures saisies", "Heures validées", "Heures au-delà du prévu", "Retards (min)", "Absences", "Dimanches planifiés"] + (["Coût horaire (CHF)"] if see_money else [])
    return _csv(f"paie-{month}.csv", head, sorted(rows, key=lambda r: r[1]))


@router.get("/reports/billing.csv")
def billing_csv(month: str = Query(...), ctx: Ctx = Depends(require("export.run"))):
    """Données pour la facturation par client et marque ; un montant n'apparaît que si le tarif est renseigné."""
    if not has_permission(ctx.user.role, "finance.read"):
        raise HTTPException(403, "Permission requise : finance.read")
    rep = finance_report(ctx, parse_month(month), True)
    _job(ctx, "billing_csv", {"month": month})
    rows = [[r.get("client") or "Sans client", r["name"], r["planned_minutes"] / 60, r["actual_minutes"] / 60, r["validated_minutes"] / 60,
             _money(r["billable_planned_cents"]), _money(r["billable_actual_cents"]), "oui" if r["bill_missing_minutes"] else "non"] for r in rep["by_brand"]]
    return _csv(f"facturation-{month}.csv", ["Client", "Marque", "Heures planifiées", "Heures saisies", "Heures validées", "Montant prévu (CHF)", "Montant réalisé (CHF)", "Tarif manquant"], rows)


@router.get("/reports/coverage.csv")
def coverage_csv(month: str = Query(...), ctx: Ctx = Depends(require("export.run"))):
    first = parse_month(month)
    last = (first.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    assigned = set(ctx.db.scalars(select(m.Assignment.shift_id)))
    emp_of = {a.shift_id: a.employee_id for a in ctx.db.scalars(select(m.Assignment))}
    emps = {e.id: e.name for e in ctx.db.scalars(select(m.Employee))}
    rows = [[s.day.isoformat(), s.site_code, s.start_time.isoformat()[:5], s.end_time.isoformat()[:5], s.effective_minutes / 60, "couvert" if s.id in assigned else "non couvert", emps.get(emp_of.get(s.id), "")]
            for s in ctx.db.scalars(select(m.Shift).where(m.Shift.day >= first, m.Shift.day <= last).order_by(m.Shift.day, m.Shift.site_code, m.Shift.start_time))]
    _job(ctx, "coverage_csv", {"month": month})
    return _csv(f"couverture-{month}.csv", ["Date", "Site", "Début", "Fin", "Heures", "État", "Collaborateur"], rows)




@router.get("/reports/fairness")
def fairness(to: str, months: int = Query(6, ge=1, le=12), ctx: Ctx = Depends(require("reports.read"))):
    """Équité sur plusieurs mois (plannings existants, lus en direct) : par collaborateur et par mois, travail effectif, jours travaillés,
    jours de week-end et dimanches ; totaux sur la fenêtre et écart à la moyenne de l'équipe. Une journée compte une fois."""
    from .months import MONTHS_FR
    last = parse_month(to)
    keys = []
    d = last
    for _k in range(months):
        keys.append((d.year, d.month))
        d = (d - timedelta(days=1)).replace(day=1)
    keys.reverse()
    lo = date(*keys[0], 1)
    hi = (last.replace(day=28) + timedelta(days=4)).replace(day=1)
    per: Dict = defaultdict(lambda: defaultdict(lambda: {"minutes": 0, "days": set()}))
    for eid, day, mins in ctx.db.execute(select(m.Assignment.employee_id, m.Shift.day, m.Shift.effective_minutes).join(m.Shift, m.Shift.id == m.Assignment.shift_id)
                                         .where(m.Shift.day >= lo, m.Shift.day < hi)).all():
        cell = per[eid][(day.year, day.month)]
        cell["minutes"] += mins
        cell["days"].add(day)
    emps = {e.id: e for e in ctx.db.scalars(select(m.Employee))}
    rows = []
    for eid, cells in per.items():
        e = emps.get(eid)
        if e is None:
            continue
        by_month = []
        tot = {"minutes": 0, "days": 0, "weekends": 0, "sundays": 0}
        for k in keys:
            c = cells.get(k, {"minutes": 0, "days": set()})
            v = {"minutes": c["minutes"], "days": len(c["days"]), "weekends": sum(1 for x in c["days"] if x.weekday() >= 5),
                 "sundays": sum(1 for x in c["days"] if x.weekday() == 6)}
            by_month.append(v)
            for f in tot:
                tot[f] += v[f]
        rows.append({"employee_id": str(eid), "employee": e.name, "deleted": e.deleted_at is not None, "months": by_month, "total": tot})
    rows.sort(key=lambda r: r["employee"].lower())
    n = len(rows) or 1
    mean = {f: round(sum(r["total"][f] for r in rows) / n, 1) for f in ("minutes", "days", "weekends", "sundays")}
    for r in rows:
        r["delta"] = {f: round(r["total"][f] - mean[f], 1) for f in mean}
    return {"months": [{"key": f"{y}-{mo:02d}", "label": f"{MONTHS_FR[mo - 1]} {y}"} for y, mo in keys], "mean": mean, "employees": rows,
            "note": "Une journée compte une fois. Les mois sans planning comptent zéro. Le moteur tient compte des week-ends et dimanches des 3 mois précédents."}
