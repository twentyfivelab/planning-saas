"""Cycle de vie d'un planning : versions, validation, publication volontaire, restauration ; notifications et planning du collaborateur."""
import uuid
from datetime import date, datetime, time, timezone
from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from planning_solver.timecalc import shift_hours

from .. import models as m
from ..deps import Ctx, audit, get_or_404, require
from ..limits import guard_monthly_cap, month_minutes
from ..optimize import ensure_frozen
from ..period_state import ensure_editable
from ..versioning import AUTOMATIC_KINDS, apply_retention, current_map, make_version, retention_candidates, snapshot_map
from .planning import _conflicts

router = APIRouter(tags=["versions et publication"])
STATE_LABEL = {"snapshot": "Copie de travail", "in_review": "En cours de validation", "validated": "Validée", "published": "Publiée", "superseded": "Remplacée"}
KIND_LABEL = {"manual": "Manuelle", "generated": "Générée", "safety": "Copie de sécurité"}


def _view(v: m.ScheduleVersion, names: Optional[dict] = None) -> dict:
    names = names or {}
    return {"id": str(v.id), "number": v.number, "label": v.label, "published": v.published, "state": v.state, "state_label": STATE_LABEL.get(v.state, v.state), "kind": v.kind,
            "kind_label": KIND_LABEL.get(v.kind, v.kind), "exploratory": v.exploratory, "created_at": v.created_at, "assignments": len(v.snapshot or []), "note": v.note,
            "created_by": names.get(v.created_by), "validated_by": names.get(v.validated_by), "validated_at": v.validated_at, "published_by": names.get(v.published_by), "published_at": v.published_at}


class VersionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: Optional[str] = Field(None, max_length=100)
    note: Optional[str] = Field(None, max_length=300)


@router.post("/periods/{pid}/versions", status_code=201)
def create_version(pid: str, body: Optional[VersionIn] = None, label: Optional[str] = None, ctx: Ctx = Depends(require("planning.edit"))):
    p = get_or_404(ctx, m.PlanningPeriod, pid)
    v = make_version(ctx.db, ctx.tenant_id, p.id, (body.label if body else None) or label, "manual", ctx.user.id, note=body.note if body else None)
    audit(ctx, "version.create", "version", v.id, {"number": v.number, "label": v.label})
    return _view(v)


@router.get("/periods/{pid}/versions")
def versions(pid: str, ctx: Ctx = Depends(require("planning.read"))):
    p = get_or_404(ctx, m.PlanningPeriod, pid)
    names = {u.id: u.name for u in ctx.db.scalars(select(m.User))}
    current = current_map(ctx.db, p.id)
    rows = []
    for v in ctx.db.scalars(select(m.ScheduleVersion).where(m.ScheduleVersion.period_id == p.id).order_by(m.ScheduleVersion.number)):
        rows.append({**_view(v, names), "same_as_current": snapshot_map(v.snapshot or []) == current})
    return rows


def _ensure_same(ctx: Ctx, v: m.ScheduleVersion, action: str) -> None:
    """On valide et on publie ce qui est réellement dans le planning : une version dépassée ne peut pas être communiquée."""
    if snapshot_map(v.snapshot or []) != current_map(ctx.db, v.period_id):
        raise HTTPException(409, f"Le planning a changé depuis cette version : créez une nouvelle version avant de la {action}.")


@router.post("/versions/{vid}/submit")
def submit(vid: str, ctx: Ctx = Depends(require("planning.edit"))):
    v = get_or_404(ctx, m.ScheduleVersion, vid)
    if v.state != "snapshot":
        raise HTTPException(409, "Seule une copie de travail peut être soumise à validation.")
    _ensure_same(ctx, v, "soumettre")
    v.state = "in_review"
    audit(ctx, "version.submit", "version", v.id, {"number": v.number})
    ctx.db.flush()
    return _view(v)


@router.post("/versions/{vid}/validate")
def validate_version(vid: str, ctx: Ctx = Depends(require("planning.validate"))):
    v = get_or_404(ctx, m.ScheduleVersion, vid)
    if v.state not in ("snapshot", "in_review"):
        raise HTTPException(409, "Cette version est déjà validée, publiée ou remplacée.")
    _ensure_same(ctx, v, "valider")
    bad = _conflicts(ctx, v.period_id)
    if bad:
        raise HTTPException(409, detail={"code": "hard_violations", "message": f"{len(bad)} contrainte(s) stricte(s) non respectée(s) : validation refusée.", "violations": bad[:20]})
    v.state, v.validated_by, v.validated_at = "validated", ctx.user.id, datetime.now(timezone.utc)
    audit(ctx, "version.validate", "version", v.id, {"number": v.number})
    ctx.db.flush()
    return _view(v)


def _changes_by_employee(before: list, after: list) -> Dict[str, Dict[str, int]]:
    """Par collaborateur : shifts ajoutés, retirés, horaires ou sites modifiés entre deux versions publiées."""
    a = {x["slot_key"]: x for x in before}
    b = {x["slot_key"]: x for x in after}
    out: Dict[str, Dict[str, int]] = {}

    def bump(emp, key):
        if emp:
            out.setdefault(emp, {"added": 0, "removed": 0, "time": 0, "site": 0})[key] += 1

    for k, x in b.items():
        o = a.get(k)
        if o is None or (o.get("employee_id") or o["employee"]) != (x.get("employee_id") or x["employee"]):
            bump(x.get("employee_id"), "added")
            if o is not None:
                bump(o.get("employee_id"), "removed")
        else:
            if (o["start"], o["end"]) != (x["start"], x["end"]):
                bump(x.get("employee_id"), "time")
            if o.get("site") != x.get("site"):
                bump(x.get("employee_id"), "site")
    for k, o in a.items():
        if k not in b:
            bump(o.get("employee_id"), "removed")
    return out


def _summary(c: Dict[str, int]) -> str:
    parts = []
    for key, one, many in (("added", "shift ajouté", "shifts ajoutés"), ("removed", "shift retiré", "shifts retirés"), ("time", "horaire modifié", "horaires modifiés"), ("site", "changement de site", "changements de site")):
        if c.get(key):
            parts.append(f"{c[key]} {one if c[key] == 1 else many}")
    return ", ".join(parts)


class PublishIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    notify: bool = True


@router.post("/versions/{vid}/publish")
def publish(vid: str, body: Optional[PublishIn] = None, ctx: Ctx = Depends(require("planning.publish"))):
    """Acte volontaire du manager. Refusé si le planning repose sur des données incomplètes, s'il a changé depuis la version ou si une
    contrainte stricte n'est pas respectée. Une seule notification par collaborateur concerné, même après de nombreuses modifications."""
    v = get_or_404(ctx, m.ScheduleVersion, vid)
    if v.state == "superseded":
        raise HTTPException(409, "Cette version a été remplacée : créez-en une nouvelle à partir du planning actuel.")
    if v.published:
        raise HTTPException(409, "Cette version est déjà publiée.")
    if v.exploratory:
        raise HTTPException(409, "Simulation exploratoire : contrats/besoins incomplets, publication refusée "
                                 "(un planning validable exige des données complètes).")
    _ensure_same(ctx, v, "publier")
    if _conflicts(ctx, v.period_id):
        raise HTTPException(409, "Des violations de contraintes dures subsistent")
    p = ctx.db.get(m.PlanningPeriod, v.period_id)
    previous = list(ctx.db.scalars(select(m.ScheduleVersion).where(m.ScheduleVersion.period_id == v.period_id, m.ScheduleVersion.state == "published")))
    base = max(previous, key=lambda x: x.number).snapshot if previous else []
    for o in previous:
        o.state, o.published = "superseded", False
    now = datetime.now(timezone.utc)
    v.published, v.published_at, v.published_by, v.state = True, now, ctx.user.id, "published"
    sent = 0
    if body is None or body.notify:
        changes = _changes_by_employee(base, v.snapshot or [])
        users = {u.employee_id: u for u in ctx.db.scalars(select(m.User).where(m.User.employee_id.is_not(None), m.User.is_active.is_(True)))}
        for eid, c in changes.items():
            u = users.get(uuid.UUID(eid))
            if u is None:
                continue
            first = not previous
            ctx.db.add(m.Notification(tenant_id=ctx.tenant_id, user_id=u.id, kind="planning_published" if first else "planning_changed",
                                      title=f"Nouveau planning disponible — {p.name}" if first else f"Votre planning a changé — {p.name}",
                                      body=_summary(c) if not first else f"{c['added']} shift(s) planifié(s).", payload={"period_id": str(p.id), "version": v.number, **c}))
            sent += 1
    ctx.db.flush()
    audit(ctx, "version.publish", "version", v.id, {"number": v.number, "period": p.name, "notifications": sent})
    return {**_view(v), "notifications": sent}


@router.get("/versions/compare")
def compare(a: str, b: str, ctx: Ctx = Depends(require("planning.read"))):
    va, vb = get_or_404(ctx, m.ScheduleVersion, a), get_or_404(ctx, m.ScheduleVersion, b)
    A = {x["slot_key"]: x["employee"] for x in va.snapshot}
    B = {x["slot_key"]: x["employee"] for x in vb.snapshot}
    return {"added": sorted(set(B) - set(A)), "removed": sorted(set(A) - set(B)),
            "changed": [{"slot_key": k, "from": A[k], "to": B[k]} for k in sorted(set(A) & set(B)) if A[k] != B[k]],
            "unchanged": sum(1 for k in set(A) & set(B) if A[k] == B[k])}


@router.delete("/versions/{vid}", status_code=204)
def delete_version(vid: str, ctx: Ctx = Depends(require("planning.edit"))):
    """Seule une copie de travail manuelle peut être supprimée : versions générées, copies de sécurité, versions validées ou publiées restent."""
    v = get_or_404(ctx, m.ScheduleVersion, vid)
    if v.state != "snapshot" or v.kind != "manual":
        raise HTTPException(409, "Seule une copie de travail manuelle peut être supprimée : cette version reste dans l'historique.")
    audit(ctx, "version.delete", "version", v.id, {"number": v.number, "label": v.label})
    ctx.db.delete(v)


@router.post("/versions/{vid}/restore")
def restore(vid: str, ctx: Ctx = Depends(require("planning.edit"))):
    """Remet le planning dans l'état de cette version, en UNE transaction. L'état actuel est d'abord copié : la restauration est réversible."""
    v = get_or_404(ctx, m.ScheduleVersion, vid)
    ensure_editable(ctx.db, v.period_id)
    safety = make_version(ctx.db, ctx.tenant_id, v.period_id, f"Avant restauration de la version {v.number}", "safety", ctx.user.id)
    emps_by_id = {str(e.id): e for e in ctx.db.scalars(select(m.Employee))}
    emps_by_name = {e.name: e for e in emps_by_id.values()}
    shifts = {s.slot_key: s for s in ctx.db.scalars(select(m.Shift).where(m.Shift.period_id == v.period_id))}
    existing = {a.shift_id: a for a in ctx.db.scalars(select(m.Assignment).where(m.Assignment.period_id == v.period_id))}
    wanted = {x["slot_key"]: x for x in v.snapshot or []}
    period = ctx.db.get(m.PlanningPeriod, v.period_id)
    months = {(d.year, d.month) for d in (period.start_date, period.end_date)}
    involved = {a.employee_id for a in existing.values()}
    involved |= {e.id for x in wanted.values() for e in [emps_by_id.get(x.get("employee_id") or "") or emps_by_name.get(x["employee"])] if e is not None}
    before_minutes = month_minutes(ctx.db, involved, months)
    skipped, changed = [], 0
    for key, sh in shifts.items():  # affectations absentes de la version : retirées
        a = existing.get(sh.id)
        if a is not None and key not in wanted:
            ctx.db.delete(a)
            changed += 1
    ctx.db.flush()
    for key, x in wanted.items():
        e = emps_by_id.get(x.get("employee_id") or "") or emps_by_name.get(x["employee"])
        if e is None:
            skipped.append(key)
            continue
        sh = shifts.get(key)
        if sh is None:
            if "site" not in x:  # ancienne version : le site n'était pas enregistré
                skipped.append(key)
                continue
            start, end = time.fromisoformat(x["start"]), time.fromisoformat(x["end"])
            h = shift_hours(date.fromisoformat(x["day"]), start, end, x["break_minutes"])
            sh = m.Shift(tenant_id=ctx.tenant_id, period_id=v.period_id, slot_key=key, day=date.fromisoformat(x["day"]), site_code=x["site"], start_time=start, end_time=end,
                         break_minutes=x["break_minutes"], presence_minutes=h.presence_minutes, effective_minutes=h.effective_minutes)
            ctx.db.add(sh)
            ctx.db.flush()
            shifts[key] = sh
        a = existing.get(sh.id)
        if a is None:
            a = m.Assignment(tenant_id=ctx.tenant_id, period_id=v.period_id, shift_id=sh.id, employee_id=e.id, source=x.get("source", "manual"), locked=bool(x.get("locked")))
            ctx.db.add(a)
            ctx.db.flush()
            ctx.db.add(m.Break(tenant_id=ctx.tenant_id, assignment_id=a.id, minutes=sh.break_minutes, paid=False))
            for b, mi in (x.get("allocations") or {}).items():
                ctx.db.add(m.BrandAllocation(tenant_id=ctx.tenant_id, assignment_id=a.id, brand_code=b, minutes=mi))
            changed += 1
        elif a.employee_id != e.id or a.locked != bool(x.get("locked")):
            a.employee_id, a.locked = e.id, bool(x.get("locked"))
            changed += 1
    ctx.db.flush()
    guard_monthly_cap(ctx.db, ctx.tenant_id, before_minutes, involved, months)  # une version qui ferait dépasser le plafond n'est pas restaurée
    ensure_frozen(ctx.db, period)
    audit(ctx, "version.restore", "version", v.id, {"number": v.number, "changed": changed, "skipped": skipped[:50], "safety_version": safety.number})
    return {"restored": v.number, "changed": changed, "skipped": len(skipped), "safety_version": safety.number, "conflicts": _conflicts(ctx, v.period_id)}


# ---- conservation des versions automatiques ----
class RetentionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    keep_per_month: Optional[int] = Field(None, ge=2, le=1000)  # chaque génération crée 2 versions ; NULL = sans limite
    max_age_days: Optional[int] = Field(None, ge=1, le=3650)  # NULL = sans limite d'âge


def _retention_view(ctx: Ctx) -> dict:
    t = ctx.db.get(m.Tenant, ctx.tenant_id)
    months = []
    for p in ctx.db.scalars(select(m.PlanningPeriod).order_by(m.PlanningPeriod.start_date)):
        auto = len(list(ctx.db.scalars(select(m.ScheduleVersion.id).where(m.ScheduleVersion.period_id == p.id, m.ScheduleVersion.kind.in_(AUTOMATIC_KINDS), m.ScheduleVersion.state == "snapshot"))))
        months.append({"period_id": str(p.id), "name": p.name, "automatic": auto, "would_remove": len(retention_candidates(ctx.db, t, p.id)), "archived": p.archived_at is not None})
    return {"keep_per_month": t.version_keep_per_month, "max_age_days": t.version_max_age_days, "months": months}


@router.get("/settings/version-retention")
def get_retention(ctx: Ctx = Depends(require("planning.read"))):
    return _retention_view(ctx)


@router.put("/settings/version-retention")
def set_retention(body: RetentionIn, ctx: Ctx = Depends(require("planning.admin"))):
    """Règle la politique. Rien n'est retiré à l'enregistrement : elle s'applique à la prochaine génération, ou sur demande."""
    t = ctx.db.get(m.Tenant, ctx.tenant_id)
    before = {"keep_per_month": t.version_keep_per_month, "max_age_days": t.version_max_age_days}
    t.version_keep_per_month, t.version_max_age_days = body.keep_per_month, body.max_age_days
    ctx.db.flush()
    audit(ctx, "settings.version_retention", "tenant", t.id, {"before": before, "after": body.model_dump()})
    return _retention_view(ctx)


@router.post("/settings/version-retention/apply")
def run_retention(ctx: Ctx = Depends(require("planning.admin"))):
    removed = {}
    for p in ctx.db.scalars(select(m.PlanningPeriod)):
        numbers = apply_retention(ctx.db, ctx.tenant_id, p.id, ctx.user.id)
        if numbers:
            removed[p.name] = numbers
    return {"removed": removed, **_retention_view(ctx)}


class PurgeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm: bool


@router.post("/periods/{pid}/versions/purge-automatic")
def purge_automatic(pid: str, body: PurgeIn, ctx: Ctx = Depends(require("planning.admin"))):
    """Retire toutes les copies automatiques de ce mois. Le planning, les copies manuelles et toute version soumise, validée, publiée ou remplacée restent."""
    p = get_or_404(ctx, m.PlanningPeriod, pid)
    ensure_editable(ctx.db, p.id)
    if not body.confirm:
        raise HTTPException(422, "Confirmation requise.")
    rows = list(ctx.db.scalars(select(m.ScheduleVersion).where(m.ScheduleVersion.period_id == p.id, m.ScheduleVersion.kind.in_(AUTOMATIC_KINDS), m.ScheduleVersion.state == "snapshot")))
    numbers = sorted(v.number for v in rows)
    for v in rows:
        ctx.db.delete(v)
    ctx.db.flush()
    audit(ctx, "version.purge_automatic", "period", p.id, {"period": p.name, "removed": numbers})
    return {"removed": len(numbers), "numbers": numbers}


# ---- notifications ----
@router.get("/notifications")
def notifications(unread: bool = False, limit: int = 50, ctx: Ctx = Depends(require("self.read"))):
    q = select(m.Notification).where(m.Notification.user_id == ctx.user.id).order_by(m.Notification.created_at.desc()).limit(min(max(limit, 1), 200))
    if unread:
        q = q.where(m.Notification.read_at.is_(None))
    rows = list(ctx.db.scalars(q))
    n = len(list(ctx.db.scalars(select(m.Notification.id).where(m.Notification.user_id == ctx.user.id, m.Notification.read_at.is_(None)))))
    return {"unread": n, "items": [{"id": str(x.id), "kind": x.kind, "title": x.title, "body": x.body, "payload": x.payload, "read": x.read_at is not None, "at": x.created_at.isoformat()} for x in rows]}


@router.post("/notifications/read-all")
def read_all(ctx: Ctx = Depends(require("self.read"))):
    now, n = datetime.now(timezone.utc), 0
    for x in ctx.db.scalars(select(m.Notification).where(m.Notification.user_id == ctx.user.id, m.Notification.read_at.is_(None))):
        x.read_at = now
        n += 1
    return {"read": n}


@router.post("/notifications/{nid}/read")
def read_one(nid: str, ctx: Ctx = Depends(require("self.read"))):
    x = get_or_404(ctx, m.Notification, nid)
    if x.user_id != ctx.user.id:  # la notification d'un autre utilisateur n'existe pas pour moi
        raise HTTPException(404, "Introuvable")
    x.read_at = x.read_at or datetime.now(timezone.utc)
    return {"id": str(x.id), "read": True}


# ---- planning du collaborateur : uniquement ce qui a été publié ----
@router.get("/me/planning")
def my_planning(ctx: Ctx = Depends(require("self.read"))):
    """Un planning en préparation n'est jamais visible par les collaborateurs : seules les versions publiées les concernant."""
    eid = ctx.user.employee_id
    if eid is None:
        return {"linked": False, "periods": []}
    e = ctx.db.get(m.Employee, eid)
    out = []
    for p in ctx.db.scalars(select(m.PlanningPeriod).order_by(m.PlanningPeriod.start_date)):
        v = ctx.db.scalar(select(m.ScheduleVersion).where(m.ScheduleVersion.period_id == p.id, m.ScheduleVersion.state == "published").order_by(m.ScheduleVersion.number.desc()).limit(1))
        if v is None:
            continue
        mine = [x for x in (v.snapshot or []) if x.get("employee_id") == str(eid) or (not x.get("employee_id") and e and x["employee"] == e.name)]
        out.append({"period_id": str(p.id), "name": p.name, "version": v.number, "published_at": v.published_at, "minutes": sum(x.get("effective_minutes", 0) for x in mine),
                    "shifts": [{k: x.get(k) for k in ("day", "site", "start", "end", "break_minutes", "effective_minutes", "allocations")} for x in mine]})
    return {"linked": True, "employee": e.name if e else None, "periods": out}
