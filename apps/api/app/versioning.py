"""Versions d'un planning : copies immuables, créées à la demande ou automatiquement avant et après toute opération qui remplace
des affectations. Une version validée ou publiée n'est jamais modifiée : on en crée une autre. Une restauration est toujours réversible."""
import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from sqlalchemy import func, select

from . import models as m


def current_map(db, period_id) -> Dict[str, str]:
    """État courant du planning : shift -> id du collaborateur (empreinte et comparaison)."""
    rows = db.execute(select(m.Shift.slot_key, m.Assignment.employee_id).join(m.Assignment, m.Assignment.shift_id == m.Shift.id).where(m.Shift.period_id == period_id)).all()
    return {k: str(e) for k, e in rows}


def fingerprint(mapping: Dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(sorted(mapping.items())).encode()).hexdigest()


def snapshot_of(db, period_id) -> List[dict]:
    emps = {e.id: e for e in db.scalars(select(m.Employee))}
    shifts = {s.id: s for s in db.scalars(select(m.Shift).where(m.Shift.period_id == period_id))}
    rows = list(db.scalars(select(m.Assignment).where(m.Assignment.period_id == period_id)))
    allocs: Dict = {}
    if rows:
        for r in db.scalars(select(m.BrandAllocation).where(m.BrandAllocation.assignment_id.in_([a.id for a in rows]))):
            allocs.setdefault(r.assignment_id, {})[r.brand_code] = r.minutes
    out = []
    for a in rows:
        s, e = shifts[a.shift_id], emps[a.employee_id]
        out.append({"slot_key": s.slot_key, "employee": e.name, "employee_id": str(e.id), "employee_code": e.code, "day": s.day.isoformat(), "site": s.site_code,
                    "start": s.start_time.isoformat(), "end": s.end_time.isoformat(), "break_minutes": s.break_minutes, "presence_minutes": s.presence_minutes,
                    "effective_minutes": s.effective_minutes, "locked": a.locked, "source": a.source, "allocations": allocs.get(a.id, {})})
    return sorted(out, key=lambda r: (r["day"], r["start"], r["slot_key"]))


def snapshot_map(snapshot: List[dict]) -> Dict[str, str]:
    return {x["slot_key"]: x.get("employee_id") or x["employee"] for x in snapshot}


def is_exploratory(db, period_id) -> bool:
    """Exploratoire tant que le dernier calcul appliqué à CE mois repose sur des données incomplètes (contrats manquants)."""
    last = db.scalar(select(m.OptimizationResult).join(m.OptimizationRun, m.OptimizationRun.id == m.OptimizationResult.run_id)
                     .where(m.OptimizationRun.period_id == period_id, m.OptimizationRun.simulation.is_(False) | m.OptimizationRun.applied_at.is_not(None))
                     .order_by(m.OptimizationResult.created_at.desc()).limit(1))
    return last is None or last.mode != "validable"


AUTOMATIC_KINDS = ("safety", "generated")


def _automatic(db, period_id) -> List[m.ScheduleVersion]:
    """Versions que la conservation peut retirer : créées par le système et jamais soumises, validées ni publiées."""
    return list(db.scalars(select(m.ScheduleVersion).where(m.ScheduleVersion.period_id == period_id, m.ScheduleVersion.kind.in_(AUTOMATIC_KINDS),
                                                           m.ScheduleVersion.state == "snapshot").order_by(m.ScheduleVersion.number.desc())))


def retention_candidates(db, tenant: m.Tenant, period_id) -> List[m.ScheduleVersion]:
    """Versions automatiques au-delà de la politique : les plus récentes sont gardées ; la dernière n'est jamais retirée pour cause d'ancienneté."""
    p = db.get(m.PlanningPeriod, period_id)
    if p is None or p.archived_at is not None:  # un planning archivé reste figé, ses versions comprises
        return []
    rows = _automatic(db, period_id)
    keep, age = tenant.version_keep_per_month, tenant.version_max_age_days
    out = rows[keep:] if keep is not None else []
    if age is not None:
        limit = datetime.now(timezone.utc) - timedelta(days=age)
        out += [v for v in rows[1:] if v.created_at is not None and v.created_at < limit and v not in out]
    return out


def apply_retention(db, tenant_id, period_id, user_id=None) -> List[int]:
    """Applique la politique à un mois ; chaque retrait est tracé (numéros de version). Renvoie les numéros retirés."""
    tenant = db.get(m.Tenant, tenant_id)
    if tenant is None:
        return []
    rows = retention_candidates(db, tenant, period_id)
    numbers = sorted(v.number for v in rows)
    for v in rows:
        db.delete(v)
    if numbers:
        db.add(m.AuditLog(tenant_id=tenant_id, user_id=user_id, action="version.retention", entity="period", entity_id=str(period_id),
                          detail={"removed": numbers, "keep_per_month": tenant.version_keep_per_month, "max_age_days": tenant.version_max_age_days}))
        db.flush()
    return numbers


def version_context(db, period_id, snapshot: List[dict], run_id=None) -> dict:
    """Contexte de génération figé avec la version : l'entrée complète du moteur telle qu'elle s'applique à CE planning au moment de la
    version (paramètres conservés par le planning, données du mois, verrous de la version). Pour une version issue d'un calcul : les
    réglages de ce calcul (choix des paramètres, plafond actuel, pondérations exceptionnelles)."""
    from planning_solver.serialize import ENGINE_VERSION, input_to_dict
    from .services_bridge import build_input
    period = db.get(m.PlanningPeriod, period_id)
    flags: dict = {}
    run = db.get(m.OptimizationRun, run_id) if run_id else None
    if run is not None:
        flags = {**(run.config or {}), "cap": "current", "generation": True}
    inp = build_input(db, period, flags)
    inp.locked = {x["slot_key"]: x["employee_code"] for x in snapshot if x.get("locked") and x.get("employee_code")}
    return {"format": 1, "engine_version": ENGINE_VERSION, "created_at": datetime.now(timezone.utc).isoformat(),
            "params": {"mode": "current" if flags.get("params") == "current" or not period.frozen_params else "frozen",
                       "frozen_at": period.frozen_at.isoformat() if period.frozen_at else None, "source": period.frozen_source},
            "run": {"id": str(run.id), "kind": run.kind, "config": run.config} if run is not None else None,
            "input": input_to_dict(inp)}


def make_version(db, tenant_id, period_id, label: Optional[str], kind: str = "manual", user_id=None, run_id=None, note: Optional[str] = None) -> m.ScheduleVersion:
    n = (db.scalar(select(func.max(m.ScheduleVersion.number)).where(m.ScheduleVersion.period_id == period_id)) or 0) + 1
    snap = snapshot_of(db, period_id)
    ctx = version_context(db, period_id, snap, run_id)
    v = m.ScheduleVersion(tenant_id=tenant_id, period_id=period_id, number=n, label=label, snapshot=snap, exploratory=is_exploratory(db, period_id),
                          created_by=user_id, kind=kind, run_id=run_id, note=note, state="snapshot", context=ctx,
                          context_hash=hashlib.sha256(json.dumps(ctx["input"], sort_keys=True).encode()).hexdigest(), engine_version=ctx["engine_version"])
    db.add(v)
    db.flush()
    if kind in AUTOMATIC_KINDS:
        apply_retention(db, tenant_id, period_id, user_id)
    return v


def _check(inp, snapshot: List[dict]) -> dict:
    """Vérificateur indépendant sur les affectations de la version, avec les horaires de la version (jamais ceux d'aujourd'hui)."""
    import dataclasses
    from datetime import date, time
    from planning_solver.compat import compatibility
    from planning_solver.model import Assignment as SAssign
    slots = {s.id: s for s in inp.slots}
    emps = {e.id for e in inp.employees}
    assigns, unchecked = [], 0
    for x in snapshot:
        s, code = slots.get(x["slot_key"]), x.get("employee_code")
        if s is None or code not in emps:
            unchecked += 1
            continue
        s2 = dataclasses.replace(s, start=time.fromisoformat(x["start"]), end=time.fromisoformat(x["end"]), break_minutes=x["break_minutes"])
        slots[s.id] = s2
        assigns.append(SAssign(s.id, code, date.fromisoformat(x["day"]), s2.start, s2.end, x["presence_minutes"], x["break_minutes"],
                               x["effective_minutes"], dict(x.get("allocations") or s2.allocations), bool(x.get("locked"))))
    inp.slots = list(slots.values())
    rep = compatibility(inp, assigns)
    hard = [i for i in rep["items"] if i["kind"] == "obligatoire"]
    return {"status": "non_conforme" if hard else "conforme", "violations": len(hard), "preferences": len(rep["items"]) - len(hard),
            "checked": len(assigns), "unchecked": unchecked, "items": [{k: i[k] for k in ("code", "rule", "employee", "reason")} for i in hard[:30]]}


def version_conformity(v: m.ScheduleVersion, current_inp=None) -> dict:
    """Conformité INFORMATIVE (rien n'est modifié) : 1) aux règles de sa création (contexte figé) ; 2) aux règles actuelles, datée.
    Sans contexte figé : « contexte incomplet » (aucune conformité supposée)."""
    from copy import deepcopy
    from planning_solver.serialize import input_from_dict
    snap = v.snapshot or []
    if v.context and v.context.get("input"):
        creation = {**_check(input_from_dict(v.context["input"]), snap), "engine_version": v.engine_version}
    else:
        creation = {"status": "contexte_incomplet", "violations": None, "checked": 0, "unchecked": len(snap), "items": [],
                    "message": "Version antérieure à la conservation du contexte : conformité à ses règles de création non vérifiable."}
    current = None
    if current_inp is not None:
        current = {**_check(deepcopy(current_inp), snap), "checked_at": datetime.now(timezone.utc).isoformat()}
    return {"creation": creation, "current": current}
