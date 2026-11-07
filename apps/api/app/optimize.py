"""Exécution d'une optimisation (worker RQ ou inline)."""
import copy
import threading
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select

from planning_solver import solve
from planning_solver.context import prepare
from planning_solver.metrics import plan_metrics
from planning_solver.model import OutsideShift
from planning_solver.strategies import BY_KEY as STRATEGIES
from planning_solver.validator import validate
from planning_solver.weights import breakdown

from . import models as m
from . import realtime  # noqa: F401  (le worker annonce aussi la fin des générations)
from .config import settings
from .db import tenant_session
from .services_bridge import assignments_for_validation, build_input, current_assignments, persist_result
from .versioning import current_map, fingerprint, make_version


def enqueue(tenant_id: str, run_id: str) -> None:
    if settings.opt_execution == "inline":
        run_optimization(tenant_id, run_id)
        return
    from redis import Redis
    from rq import Queue
    Queue("optimization", connection=Redis.from_url(settings.redis_url)).enqueue(
        "app.optimize.run_optimization", tenant_id, run_id, job_timeout=1800)


def _jsonable(o):
    import dataclasses
    from datetime import date, time
    if dataclasses.is_dataclass(o):
        return {k: _jsonable(v) for k, v in dataclasses.asdict(o).items()}
    if isinstance(o, dict):
        return {str(k): _jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple, set)):
        return [_jsonable(v) for v in o]
    if isinstance(o, (date, time, datetime)):
        return o.isoformat()
    return o


def _freeze_outside_scope(inp, prev: dict, locked: dict, config: dict) -> dict:
    """Réoptimisation localisée : seuls les shifts du périmètre sont libres ; tout le reste est figé tel quel (affecté ou vide). Un verrou
    n'est levé que si son titulaire ne peut plus assurer le shift. Renvoie les verrous conservés par le solveur."""
    from datetime import date, timedelta
    free = set(config.get("free_slots", []))
    radius = int(config.get("radius_days") or 0)
    if radius:
        days = {date.fromisoformat(d) for d in config.get("free_days", [])}
        near = {d + timedelta(days=k) for d in days for k in range(-radius, radius + 1)}
        free |= {s.id for s in inp.slots if s.day in near and s.id not in locked}
    prep = prepare(inp)
    slots = {s.id: s for s in inp.slots}
    fixed, removed = {}, []
    for sid, eid in prev.items():
        if sid not in slots:
            continue
        if sid in free and sid not in locked:
            continue
        if (eid, sid) in prep.eligible:
            fixed[sid] = eid
        elif sid in locked and sid in free:
            continue  # le titulaire ne peut plus assurer ce shift verrouillé : le manager l'a inclus dans le périmètre
        elif sid in locked:
            removed.append(sid)  # dérogation enregistrée, hors périmètre : conservée et comptée comme shift déjà planifié
        else:
            free.add(sid)  # le titulaire ne peut plus l'assurer : à réaffecter, le figer rendrait le problème impossible
    for sid in removed:
        s = slots[sid]
        inp.outside_shifts.append(OutsideShift(prev[sid], s.day, s.start, s.end, s.effective_minutes))
    if removed:
        gone = set(removed)
        inp.slots = [s for s in inp.slots if s.id not in gone]
    inp.frozen_empty = {s.id for s in inp.slots if s.id not in free and s.id not in fixed}
    return fixed


class PlanRejected(Exception):
    """Le planning enregistré enfreint une contrainte stricte : la transaction d'enregistrement est annulée."""

    def __init__(self, violations):
        super().__init__("planning rejeté")
        self.violations = violations


def verify_on_fresh_data(db, period, config: dict, plan: list, kept_locks: dict) -> list:
    """Vérificateur indépendant sur les données RELUES après le calcul : une absence saisie pendant le calcul, un besoin retiré ou un verrou posé entre-temps est détecté."""
    fresh = build_input(db, period, config)
    known = {s.id for s in fresh.slots}
    gone = [f"BESOIN_RETIRE: {a.slot_id} n'existe plus" for a in plan if a.slot_id not in known]
    fresh.locked = dict(kept_locks)
    return gone + validate(fresh, [a for a in plan if a.slot_id in known])


def verify_saved_plan(db, period, config: dict, before: set) -> dict:
    """Vérificateur indépendant sur le planning réellement enregistré. Seules les violations nouvelles le font rejeter (une dérogation déjà accordée reste signalée)."""
    fresh = build_input(db, period, config)
    saved = assignments_for_validation(db, fresh, period)
    found = set(validate(fresh, saved))
    n_rows = db.scalar(select(func.count()).select_from(m.Assignment).where(m.Assignment.period_id == period.id)) or 0
    return {"checked": len(saved), "unchecked": n_rows - len(saved), "violations": sorted(found - before), "already_known": len(found & before)}


def run_optimization(tenant_id: str, run_id: str) -> None:
    cancel = threading.Event()
    stop = threading.Event()

    def watch():  # relaie cancel_requested (base) vers le solveur
        while not stop.wait(1.0):
            with tenant_session(tenant_id) as db:
                r = db.get(m.OptimizationRun, uuid.UUID(run_id))
                if r is not None and r.cancel_requested:
                    cancel.set()
                    return

    try:
        with tenant_session(tenant_id) as db:
            run = db.get(m.OptimizationRun, uuid.UUID(run_id))
            if run is None or run.cancel_requested:
                if run is not None:
                    run.status = "annule"
                return
            run.status, run.started_at = "en_cours", datetime.now(timezone.utc)
            period = db.get(m.PlanningPeriod, run.period_id)
            inp = build_input(db, period, run.config)
            prev, locked = current_assignments(db, period)
            simulation, config = run.simulation, dict(run.config or {})
            keep_current = run.kind in ("partial", "local") or STRATEGIES.get(config.get("strategy"), {}).get("keep_current", False)
            inp.previous = prev if keep_current else {}
            inp.locked = _freeze_outside_scope(inp, prev, locked, config) if run.kind == "local" else locked
            base_fp = fingerprint(current_map(db, period.id))
            before_plan = build_input(db, period, run.config)
            before_violations = set(validate(before_plan, assignments_for_validation(db, before_plan, period)))
            used_locks = dict(inp.locked)
        threading.Thread(target=watch, daemon=True).start()
        res = solve(inp, cancel)
        stop.set()
        with tenant_session(tenant_id) as db:
            run = db.get(m.OptimizationRun, uuid.UUID(run_id))
            period = db.get(m.PlanningPeriod, run.period_id)
            report = _jsonable({k: v for k, v in res.to_dict().items() if k != "assignments"})
            report["weights_used"] = res.weights
            report["criteria_scores"] = breakdown(res.objective)  # coût par critère : quels critères ont influencé le choix
            # vérification indépendante, sans exception dès qu'un planning existe (optimal, valide, partiel, interrompu, simulation, réoptimisation)
            verification = {"executed": bool(res.assignments), "status": res.status, "kind": run.kind, "simulation": simulation,
                            "solver_result": {"checked": len(res.assignments), "violations": list(res.hard_violations)}}
            if res.assignments:
                fresh_violations = verify_on_fresh_data(db, period, config, res.assignments, used_locks)
                verification["fresh_data"] = {"checked": len(res.assignments), "violations": fresh_violations}
                new = [v for v in fresh_violations if v not in res.hard_violations and v not in before_violations]
                if new:
                    res.hard_violations = list(res.hard_violations) + new
                    report["hard_violations"] = res.hard_violations
            else:
                verification["reason"] = "Aucun planning produit : rien à vérifier, rien n'est enregistré."
            report["verification"] = verification
            if simulation:  # une simulation n'écrit JAMAIS dans le planning : elle garde sa proposition jusqu'à une application explicite
                report["base_fingerprint"] = base_fp
                known = {s.id for s in inp.slots}
                reference = {k: v for k, v in prev.items() if k in known} if run.kind == "local" else prev
                report["metrics"] = _jsonable(plan_metrics(inp, res.assignments, reference=reference)) if res.assignments else _jsonable(res.metrics)
                if not res.hard_violations:
                    report["proposal"] = [{"slot_id": a.slot_id, "employee_id": a.employee_id, "day": a.day.isoformat(), "start": a.start.isoformat()[:5], "end": a.end.isoformat()[:5],
                                           "site": next((s.site for s in inp.slots if s.id == a.slot_id), None)} for a in res.assignments]
                db.add(m.OptimizationResult(tenant_id=run.tenant_id, run_id=run.id, status=res.status, mode=res.mode, duration_s=res.duration_s, report=report))
                run.status = "annule" if cancel.is_set() else "termine"
                run.finished_at = datetime.now(timezone.utc)
                db.add(m.AuditLog(tenant_id=run.tenant_id, action="simulation.finished", entity="run", entity_id=str(run.id),
                                  detail={"status": res.status, "strategy": config.get("strategy"), "kind": run.kind}))
                return
            # ligne enregistrée tôt (le statut « exploratoire » des versions s'en sert) ; le rapport définitif est écrit en sortie
            row = m.OptimizationResult(tenant_id=run.tenant_id, run_id=run.id, status=res.status, mode=res.mode, duration_s=res.duration_s, report=copy.deepcopy(report))
            db.add(row)
            # garde-fou : un planning qui enfreint une contrainte dure n'est JAMAIS enregistré (vérification indépendante)
            if res.hard_violations:
                report["blocked_by_verification"] = res.hard_violations
                row.report = report
                db.add(m.Conflict(tenant_id=run.tenant_id, run_id=run.id, code="PLAN_REJECTED", severity="blocking",
                                  message="Planning refusé par la vérification automatique : " + "; ".join(res.hard_violations[:5]),
                                  slots=[]))
                run.status, run.finished_at = "erreur", datetime.now(timezone.utc)
                return
            if res.status in ("optimal", "faisable", "partiellement_couvert") or (
                    res.status == "interrompu" and res.assignments):
                try:
                    with db.begin_nested():  # enregistrement et vérification du planning enregistré : tout ou rien
                        if prev:  # le planning remplacé reste récupérable
                            make_version(db, run.tenant_id, period.id, "Avant génération", "safety", run.requested_by)
                        persist_result(db, run.tenant_id, period, inp, res, run.id)
                        db.flush()
                        saved = verify_saved_plan(db, period, config, before_violations)
                        verification["after_save"] = saved
                        if saved["violations"]:
                            raise PlanRejected(saved["violations"])
                        make_version(db, run.tenant_id, period.id, "Planning généré", "generated", run.requested_by, run_id=run.id)
                except PlanRejected as exc:
                    report["blocked_by_verification"] = exc.violations
                    row.report = report
                    db.add(m.Conflict(tenant_id=run.tenant_id, run_id=run.id, code="PLAN_REJECTED", severity="blocking",
                                      message="Planning refusé par la vérification du planning enregistré : " + "; ".join(exc.violations[:5]), slots=[]))
                    run.status, run.finished_at = "erreur", datetime.now(timezone.utc)
                    return
            row.report = report
            for i in res.diagnostics + res.missing_data:
                if i.severity != "info":
                    db.add(m.Conflict(tenant_id=run.tenant_id, run_id=run.id, code=i.code, severity=i.severity,
                                      message=i.message, slots=i.slots))
            run.status = "annule" if cancel.is_set() else "termine"
            run.finished_at = datetime.now(timezone.utc)
            db.add(m.AuditLog(tenant_id=run.tenant_id, action="optimization.finished", entity="run",
                              entity_id=str(run.id), detail={"status": res.status, "mode": res.mode}))
    except Exception as exc:  # noqa: BLE001 — statut d'erreur sans détail sensible
        stop.set()
        with tenant_session(tenant_id) as db:
            run = db.get(m.OptimizationRun, uuid.UUID(run_id))
            if run is not None:
                run.status, run.finished_at = "erreur", datetime.now(timezone.utc)
                db.add(m.OptimizationResult(tenant_id=run.tenant_id, run_id=run.id, status="interrompu",
                                            mode="n/a", duration_s=0.0, report={"error": type(exc).__name__}))
        raise
