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


def make_version(db, tenant_id, period_id, label: Optional[str], kind: str = "manual", user_id=None, run_id=None, note: Optional[str] = None) -> m.ScheduleVersion:
    n = (db.scalar(select(func.max(m.ScheduleVersion.number)).where(m.ScheduleVersion.period_id == period_id)) or 0) + 1
    v = m.ScheduleVersion(tenant_id=tenant_id, period_id=period_id, number=n, label=label, snapshot=snapshot_of(db, period_id), exploratory=is_exploratory(db, period_id),
                          created_by=user_id, kind=kind, run_id=run_id, note=note, state="snapshot")
    db.add(v)
    db.flush()
    if kind in AUTOMATIC_KINDS:
        apply_retention(db, tenant_id, period_id, user_id)
    return v
