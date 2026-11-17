"""Décisions assistées par le moteur : classement des remplaçants, explication d'une affectation, absence imprévue, réoptimisation
localisée, simulations de stratégies et comparaison. Une simulation n'écrit jamais dans le planning tant qu'elle n'est pas appliquée."""
import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select

from planning_solver.explain import explain_assignment
from planning_solver.metrics import plan_metrics
from planning_solver.model import Assignment as SAssign
from planning_solver.replace import rank_replacements
from planning_solver.strategies import BY_KEY as STRATEGIES, STRATEGIES as STRATEGY_LIST
from planning_solver.validator import validate

from .. import models as m
from ..deps import Ctx, audit, get_or_404, require
from ..optimize import enqueue, ensure_frozen, freeze_period, new_violations, verify_saved_plan
from ..period_state import ensure_editable, has_official_version
from ..rbac import has_permission
from ..services_bridge import assignments_for_validation, build_input, persist_result
from ..versioning import current_map, fingerprint, make_version
from .planning import _after_commit, _conflicts

router = APIRouter(tags=["décisions du moteur"])


def _state(ctx: Ctx, p: m.PlanningPeriod):
    inp = build_input(ctx.db, p, {"cap": "current"})  # remplaçants proposés : jamais au-delà du plafond mensuel actuel
    return inp, assignments_for_validation(ctx.db, inp, p)


def _ranking(ctx: Ctx, inp, base, sh: m.Shift, emps_by_code: dict, limit: Optional[int] = None) -> dict:
    if sh.slot_key not in {s.id for s in inp.slots}:
        raise HTTPException(422, "Ce shift n'est pas connu du moteur (besoin supprimé ou mission annulée).")
    r = rank_replacements(inp, base, sh.slot_key)
    see_cost = has_permission(ctx.user.role, "finance.read")
    rows = r["candidates"] if limit is None else [c for c in r["candidates"] if c["status"] == "compatible"][:limit]
    for c in rows:
        c["employee_uuid"] = str(emps_by_code[c["employee_id"]].id) if c["employee_id"] in emps_by_code else None
        if not see_cost:
            c["cost_cents"] = None
    return {**r, "candidates": rows}


@router.get("/shifts/{sid}/replacements")
def replacements(sid: str, ctx: Ctx = Depends(require("planning.read"))):
    """Remplaçants classés par le moteur : contraintes dures vérifiées, puis coût réel du changement (score explicable)."""
    sh = get_or_404(ctx, m.Shift, sid)
    p = ctx.db.get(m.PlanningPeriod, sh.period_id)
    inp, base = _state(ctx, p)
    emps = {e.code: e for e in ctx.db.scalars(select(m.Employee))}
    r = _ranking(ctx, inp, base, sh, emps)
    holder = emps.get(r["holder"]) if r["holder"] else None
    return {**r, "shift_id": str(sh.id), "day": sh.day.isoformat(), "site": sh.site_code, "start": sh.start_time.isoformat()[:5], "end": sh.end_time.isoformat()[:5],
            "holder_name": holder.name if holder else None, "holder_id": str(holder.id) if holder else None, "weights_note": "Score 100 : coût le plus faible parmi les candidats compatibles ; 0 : coût le plus élevé."}


@router.get("/assignments/{aid}/explain")
def explain(aid: str, ctx: Ctx = Depends(require("planning.read"))):
    """Pourquoi cette affectation : uniquement les règles contrôlées, les critères observés et les coûts réels du moteur."""
    a = get_or_404(ctx, m.Assignment, aid)
    sh = ctx.db.get(m.Shift, a.shift_id)
    p = ctx.db.get(m.PlanningPeriod, a.period_id)
    inp, base = _state(ctx, p)
    if sh.slot_key not in {s.id for s in inp.slots} or not any(x.slot_id == sh.slot_key for x in base):
        raise HTTPException(422, "Cette affectation ne correspond plus à un besoin du moteur : aucune explication fiable.")
    ex = explain_assignment(inp, base, sh.slot_key)
    origin = {"source": a.source, "locked": a.locked, "manual": a.source == "manual"}
    if a.run_id is not None:
        run = ctx.db.get(m.OptimizationRun, a.run_id)
        res = ctx.db.scalar(select(m.OptimizationResult).where(m.OptimizationResult.run_id == a.run_id))
        if run is not None and res is not None:
            rep = res.report or {}
            origin.update(run_id=str(run.id), run_status=res.status, proved_optimal=bool(rep.get("proved_optimal")), levels=rep.get("levels", []), run_at=run.finished_at, strategy=(run.config or {}).get("strategy"))
    return {**ex, "origin": origin, "assignment_id": str(a.id)}


class AbsenceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    employee_id: uuid.UUID
    start: date
    end: date
    reason: Optional[str] = Field(None, max_length=200)

    @model_validator(mode="after")
    def _a(self):
        if self.end < self.start:
            raise ValueError("La fin de l'absence précède son début.")
        if (self.end - self.start).days > 366:
            raise ValueError("Une absence dure au plus un an.")
        return self


def _impacted(ctx: Ctx, e: m.Employee, p: m.PlanningPeriod, start: date, end: date) -> List[tuple]:
    rows = ctx.db.execute(select(m.Assignment, m.Shift).join(m.Shift, m.Shift.id == m.Assignment.shift_id)
                          .where(m.Assignment.employee_id == e.id, m.Shift.period_id == p.id, m.Shift.day >= start, m.Shift.day <= end).order_by(m.Shift.day)).all()
    return [(a, s) for a, s in rows]


@router.post("/periods/{pid}/absences")
def declare_absence(pid: str, body: AbsenceIn, ctx: Ctx = Depends(require("availability.write"))):
    """Absence imprévue : enregistre l'indisponibilité, n'enlève aucun shift, et renvoie les shifts concernés avec les meilleurs remplaçants.
    Le manager choisit ensuite : remplacement simple, réoptimisation partielle ou complète."""
    p = get_or_404(ctx, m.PlanningPeriod, pid)
    ensure_editable(ctx.db, p.id)
    e = ctx.db.get(m.Employee, body.employee_id)
    if e is None:
        raise HTTPException(422, "Collaborateur inconnu")
    have = {u.on_date for u in ctx.db.scalars(select(m.Unavailability).where(m.Unavailability.employee_id == e.id, m.Unavailability.on_date.is_not(None)))}
    d, added = body.start, []
    while d <= body.end:
        if d not in have:
            ctx.db.add(m.Unavailability(tenant_id=ctx.tenant_id, employee_id=e.id, on_date=d, reason=body.reason or "absence"))
            added.append(d.isoformat())
        d += timedelta(days=1)
    ctx.db.flush()
    audit(ctx, "availability.absence", "employee", e.id, {"start": body.start.isoformat(), "end": body.end.isoformat(), "reason": body.reason, "added": added})
    return impact(pid, e.id, body.start, body.end, ctx)


@router.get("/periods/{pid}/absence-impact")
def impact(pid: str, employee_id: uuid.UUID, start: date, end: date, ctx: Ctx = Depends(require("planning.read"))):
    p = get_or_404(ctx, m.PlanningPeriod, pid)
    e = ctx.db.get(m.Employee, employee_id)
    if e is None:
        raise HTTPException(422, "Collaborateur inconnu")
    inp, base = _state(ctx, p)
    emps = {x.code: x for x in ctx.db.scalars(select(m.Employee))}
    shifts = []
    for a, sh in _impacted(ctx, e, p, start, end):
        r = _ranking(ctx, inp, base, sh, emps, limit=5) if sh.slot_key in {s.id for s in inp.slots} else {"candidates": [], "compatible": 0}
        shifts.append({"shift_id": str(sh.id), "assignment_id": str(a.id), "day": sh.day.isoformat(), "site": sh.site_code, "start": sh.start_time.isoformat()[:5], "end": sh.end_time.isoformat()[:5],
                       "locked": a.locked, "candidates": r["candidates"], "compatible": r["compatible"]})
    return {"employee": {"id": str(e.id), "name": e.name}, "start": start.isoformat(), "end": end.isoformat(), "shifts": shifts,
            "without_candidate": sum(1 for s in shifts if not s["compatible"])}


class LocalIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    shift_ids: List[uuid.UUID] = Field(default=[], max_length=2000)
    mission_id: Optional[uuid.UUID] = None
    employee_id: Optional[uuid.UUID] = None  # avec start/end : tous les shifts de ce collaborateur sur ces dates
    start: Optional[date] = None
    end: Optional[date] = None
    radius_days: int = Field(0, ge=0, le=7)  # étend le périmètre aux shifts des jours voisins, si un échange est nécessaire
    time_limit_s: float = Field(15, gt=0, le=300)


def _new_run(ctx: Ctx, p: m.PlanningPeriod, kind: str, config: dict) -> m.OptimizationRun:
    run = m.OptimizationRun(tenant_id=ctx.tenant_id, period_id=p.id, kind=kind, config=config, requested_by=ctx.user.id, simulation=True)
    ctx.db.add(run)
    ctx.db.flush()
    audit(ctx, "simulation.requested", "run", run.id, {"kind": kind, "strategy": config.get("strategy"), "free_slots": len(config.get("free_slots", []))})
    rid, tid = str(run.id), str(ctx.tenant_id)
    _after_commit(ctx, lambda: enqueue(tid, rid))
    return run


@router.post("/periods/{pid}/local-reoptimize", status_code=202)
def local_reoptimize(pid: str, body: LocalIn, ctx: Ctx = Depends(require("planning.optimize"))):
    """Réoptimisation partielle : seuls les shifts du périmètre (et, si demandé, ceux des jours voisins) peuvent changer ; tout le reste
    est figé. Le résultat est une proposition à comparer puis à appliquer : rien n'est modifié à ce stade."""
    p = get_or_404(ctx, m.PlanningPeriod, pid)
    ensure_editable(ctx.db, p.id)
    keys, days = set(), set()
    for sid in body.shift_ids:
        sh = ctx.db.get(m.Shift, sid)
        if sh is None or sh.period_id != p.id:
            raise HTTPException(422, "Shift inconnu pour ce mois.")
        keys.add(sh.slot_key)
        days.add(sh.day)
    if body.employee_id is not None and body.start and body.end:
        e = ctx.db.get(m.Employee, body.employee_id)
        if e is None:
            raise HTTPException(422, "Collaborateur inconnu")
        for _a, sh in _impacted(ctx, e, p, body.start, body.end):
            keys.add(sh.slot_key)
            days.add(sh.day)
    if body.mission_id is not None:
        x = ctx.db.get(m.Mission, body.mission_id)
        if x is None:
            raise HTTPException(422, "Mission inconnue")
        for s in build_input(ctx.db, p).slots:
            if s.mission == x.code:
                keys.add(s.id)
                days.add(s.day)
    if not keys:
        raise HTTPException(422, "Rien à réoptimiser : aucun shift dans le périmètre demandé.")
    config = {"time_limit_s": body.time_limit_s, "free_slots": sorted(keys), "radius_days": body.radius_days, "free_days": sorted(d.isoformat() for d in days), "label": "Réoptimisation partielle"}
    run = _new_run(ctx, p, "local", config)
    return {"run_id": str(run.id), "status": "en_attente", "free_slots": len(keys)}


class SimulationsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    strategies: List[str] = Field(min_length=1, max_length=6)
    time_limit_s: float = Field(15, gt=0, le=300)

    @model_validator(mode="after")
    def _s(self):
        bad = [k for k in self.strategies if k not in STRATEGIES]
        if bad:
            raise ValueError(f"Stratégie inconnue : {', '.join(bad)}")
        self.strategies = list(dict.fromkeys(self.strategies))
        return self


@router.get("/simulation-strategies")
def strategies(ctx: Ctx = Depends(require("planning.read"))):
    return [{k: s[k] for k in ("key", "label", "description", "keep_current")} for s in STRATEGY_LIST]


@router.post("/periods/{pid}/simulations", status_code=202)
def start_simulations(pid: str, body: SimulationsIn, ctx: Ctx = Depends(require("planning.optimize"))):
    """Lance une simulation par stratégie (dans le worker). Le planning en cours n'est jamais modifié."""
    p = get_or_404(ctx, m.PlanningPeriod, pid)
    ensure_editable(ctx.db, p.id)
    return {"runs": [{"run_id": str(_new_run(ctx, p, "simulation", {"time_limit_s": body.time_limit_s, "strategy": key, "label": STRATEGIES[key]["label"]}).id), "strategy": key} for key in body.strategies]}


def _sim_row(run: m.OptimizationRun, res: Optional[m.OptimizationResult], fp_now: str) -> dict:
    rep = (res.report or {}) if res else {}
    metrics = rep.get("metrics") or {}
    return {"run_id": str(run.id), "kind": run.kind, "strategy": (run.config or {}).get("strategy"), "label": (run.config or {}).get("label"), "status": run.status,
            "result_status": res.status if res else None, "proved_optimal": bool(rep.get("proved_optimal")), "duration_s": res.duration_s if res else None,
            "created_at": run.created_at, "applied_at": run.applied_at, "stale": bool(res and rep.get("base_fingerprint") and rep["base_fingerprint"] != fp_now),
            "hard_violations": len(rep.get("hard_violations") or []), "error": rep.get("error"), "verified": bool((rep.get("verification") or {}).get("executed")),
            "metrics": {k: metrics.get(k) for k in ("coverage_rate", "uncovered_shifts", "mandatory_shifts", "total_minutes", "gap_to_targets_minutes", "soft_unsatisfied", "soft_detail",
                                                    "sundays_min", "sundays_max", "sundays_total", "cost_cents", "cost_known_share", "changes", "objective")} if metrics else None}


@router.get("/periods/{pid}/simulations")
def simulations(pid: str, limit: int = 30, ctx: Ctx = Depends(require("planning.read"))):
    p = get_or_404(ctx, m.PlanningPeriod, pid)
    fp = fingerprint(current_map(ctx.db, p.id))
    rows = list(ctx.db.scalars(select(m.OptimizationRun).where(m.OptimizationRun.period_id == p.id, m.OptimizationRun.simulation.is_(True))
                               .order_by(m.OptimizationRun.created_at.desc()).limit(min(max(limit, 1), 100))))
    res = {r.run_id: r for r in ctx.db.scalars(select(m.OptimizationResult).where(m.OptimizationResult.run_id.in_([x.id for x in rows])))} if rows else {}
    return [_sim_row(r, res.get(r.id), fp) for r in rows]


@router.get("/periods/{pid}/metrics")
def metrics(pid: str, ctx: Ctx = Depends(require("planning.read"))):
    """Indicateurs du planning en cours, recalculés sur les affectations enregistrées (mêmes calculs que pour les simulations)."""
    p = get_or_404(ctx, m.PlanningPeriod, pid)
    inp, base = _state(ctx, p)
    return plan_metrics(inp, base)


def _sim_or_404(ctx: Ctx, rid: str):
    run = get_or_404(ctx, m.OptimizationRun, rid)
    if not run.simulation:
        raise HTTPException(404, "Introuvable")
    res = ctx.db.scalar(select(m.OptimizationResult).where(m.OptimizationResult.run_id == run.id))
    return run, res


@router.get("/simulations/{rid}")
def simulation(rid: str, ctx: Ctx = Depends(require("planning.read"))):
    """Détail : chaque shift qui changerait, du titulaire actuel au titulaire proposé, et les indicateurs par collaborateur."""
    run, res = _sim_or_404(ctx, rid)
    fp = fingerprint(current_map(ctx.db, run.period_id))
    row = _sim_row(run, res, fp)
    if res is None or not (res.report or {}).get("proposal"):
        return {**row, "changes": [], "employees": []}
    emps = {e.code: e for e in ctx.db.scalars(select(m.Employee))}
    by_id = {str(e.id): e for e in emps.values()}
    now = current_map(ctx.db, run.period_id)
    proposal = {x["slot_id"]: x for x in res.report["proposal"]}
    changes = []
    for key, x in proposal.items():
        new = emps.get(x["employee_id"])
        old = by_id.get(now.get(key, ""))
        if old is None or new is None or old.id != new.id:
            changes.append({**{k: x.get(k) for k in ("slot_id", "day", "site", "start", "end")}, "from": old.name if old else None, "to": new.name if new else x["employee_id"]})
    for key, eid in now.items():
        if key not in proposal:
            who = by_id.get(eid)
            changes.append({"slot_id": key, "day": key.rsplit("|", 1)[-1], "site": None, "start": None, "end": None, "from": who.name if who else None, "to": None})
    changes.sort(key=lambda c: (c["day"] or "", c["start"] or ""))
    metrics_ = (res.report or {}).get("metrics") or {}
    return {**row, "changes": changes[:500], "employees": metrics_.get("employees", []), "levels": res.report.get("levels", []), "diagnostics": res.report.get("diagnostics", [])}


@router.delete("/simulations/{rid}", status_code=204)
def delete_simulation(rid: str, ctx: Ctx = Depends(require("planning.optimize"))):
    """Retire une simulation de la comparaison. Une simulation appliquée reste : elle est à l'origine d'une version du planning."""
    run, _res = _sim_or_404(ctx, rid)
    if run.applied_at is not None:
        raise HTTPException(409, "Cette simulation a été appliquée : elle reste dans l'historique.")
    if run.status in ("en_attente", "en_cours"):
        raise HTTPException(409, "Calcul en cours : attendez la fin de la simulation.")
    audit(ctx, "simulation.delete", "run", run.id, {"label": (run.config or {}).get("label")})
    ctx.db.delete(run)


class ApplyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm_replace: bool = False


@router.post("/simulations/{rid}/apply")
def apply_simulation(rid: str, body: Optional[ApplyIn] = None, ctx: Ctx = Depends(require("planning.optimize"))):
    """Applique une simulation choisie par le manager : refusée si le planning a changé depuis son calcul ou si le vérificateur indépendant
    détecte une violation. L'état précédent est conservé dans une copie de sécurité."""
    run, res = _sim_or_404(ctx, rid)
    ensure_editable(ctx.db, run.period_id)
    if run.applied_at is not None:
        raise HTTPException(409, "Cette simulation a déjà été appliquée.")
    rep = (res.report if res else None) or {}
    if run.status != "termine" or not rep.get("proposal"):
        raise HTTPException(409, "Cette simulation n'a pas de résultat applicable.")
    p = ctx.db.get(m.PlanningPeriod, run.period_id)
    if has_official_version(ctx.db, p.id) and not (body and body.confirm_replace):
        raise HTTPException(409, detail={"code": "official_version", "message": f"{p.name} a une version validée ou publiée : elle reste conservée, mais le planning en cours serait remplacé. Confirmez pour continuer."})
    if rep.get("base_fingerprint") != fingerprint(current_map(ctx.db, p.id)):
        raise HTTPException(409, detail={"code": "stale", "message": "Le planning a été modifié depuis cette simulation : relancez-la pour éviter d'écraser ces modifications."})
    flags = {"cap": "current", "generation": True, **({"params": run.config["params"]} if (run.config or {}).get("params") else {})}  # mêmes paramètres que la simulation
    inp = build_input(ctx.db, p, flags)
    slots = {s.id: s for s in inp.slots}
    missing = [x["slot_id"] for x in rep["proposal"] if x["slot_id"] not in slots]
    if missing:
        raise HTTPException(409, detail={"code": "stale", "message": "Les besoins ont changé depuis cette simulation : relancez-la."})
    plan = []
    for x in rep["proposal"]:
        s = slots[x["slot_id"]]
        h = s.hours
        plan.append(SAssign(s.id, x["employee_id"], s.day, s.start, s.end, h.presence_minutes, h.break_minutes, h.effective_minutes, dict(s.allocations)))
    found = validate(inp, plan)  # avant la relecture des horaires modifiés (même ordre qu'auparavant)
    before = set(validate(inp, assignments_for_validation(ctx.db, inp, p)))
    bad = new_violations(found, before)  # un dépassement de plafond antérieur, non aggravé, n'empêche pas l'application
    if bad:
        raise HTTPException(409, detail={"code": "hard_violations", "message": f"{len(bad)} contrainte(s) stricte(s) ne seraient pas respectées : application refusée.", "violations": bad[:20]})
    safety = make_version(ctx.db, ctx.tenant_id, p.id, f"Avant application : {(run.config or {}).get('label', 'simulation')}", "safety", ctx.user.id)
    persist_result(ctx.db, ctx.tenant_id, p, inp, SimpleNamespace(assignments=plan), run.id)
    run.applied_at = datetime.now(timezone.utc)
    ctx.db.flush()
    saved = verify_saved_plan(ctx.db, p, flags, before)  # vérification du planning réellement enregistré : tout est annulé en cas de violation nouvelle
    if saved["violations"]:
        raise HTTPException(409, detail={"code": "hard_violations", "message": f"{len(saved['violations'])} contrainte(s) stricte(s) ne seraient pas respectées : application annulée.", "violations": saved["violations"][:20]})
    label = (run.config or {}).get("label", "Simulation")
    v = make_version(ctx.db, ctx.tenant_id, p.id, f"Planning généré — {label}", "generated", ctx.user.id, run_id=run.id)
    if flags.get("params") == "current":
        freeze_period(ctx.db, p, "generation", cap_used=inp.config.monthly_cap_minutes)
    else:
        ensure_frozen(ctx.db, p, "generation")
    audit(ctx, "simulation.applied", "run", run.id, {"strategy": (run.config or {}).get("strategy"), "label": label, "safety_version": safety.number, "version": v.number,
                                                     "changes": (rep.get("metrics") or {}).get("changes")})
    return {"applied": True, "version": v.number, "safety_version": safety.number, "conflicts": _conflicts(ctx, p.id)}
