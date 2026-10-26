"""Exécution d'une optimisation (worker RQ ou inline)."""
import threading
import uuid
from datetime import datetime, timezone


from planning_solver import solve

from . import models as m
from .config import settings
from .db import tenant_session
from .services_bridge import build_input, current_assignments, persist_result


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
            inp.previous = prev if run.kind == "partial" else {}
            inp.locked = locked
        threading.Thread(target=watch, daemon=True).start()
        res = solve(inp, cancel)
        stop.set()
        with tenant_session(tenant_id) as db:
            run = db.get(m.OptimizationRun, uuid.UUID(run_id))
            period = db.get(m.PlanningPeriod, run.period_id)
            report = _jsonable({k: v for k, v in res.to_dict().items() if k != "assignments"})
            report["weights_used"] = res.weights
            db.add(m.OptimizationResult(tenant_id=run.tenant_id, run_id=run.id, status=res.status, mode=res.mode,
                                        duration_s=res.duration_s, report=report))
            if res.status in ("optimal", "faisable", "partiellement_couvert") or (
                    res.status == "interrompu" and res.assignments):
                persist_result(db, run.tenant_id, period, inp, res, run.id)
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
