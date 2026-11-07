"""Clients et missions : entreprises clientes, contrats commerciaux, demandes de personnel. Une mission confirmée crée des besoins
ordinaires (`staffing_requirements`) : le moteur la planifie à côté des animations permanentes, avec les mêmes contraintes dures."""
import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select

from planning_solver.timecalc import shift_hours

from .. import models as m
from ..deps import Ctx, audit, get_or_404, require
from ..history import assignment_detail
from ..services_bridge import PLANNED_MISSION_STATUSES
from .catalog import _slug, _template
from .crud import serialize

router = APIRouter(tags=["clients et missions"])


class S(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ContactIn(S):
    name: str = Field(min_length=1, max_length=200)
    role: Optional[str] = Field(None, max_length=100)
    email: Optional[str] = Field(None, max_length=254)
    phone: Optional[str] = Field(None, max_length=50)


class ClientIn(S):
    name: str = Field(min_length=1, max_length=200)
    code: Optional[str] = Field(None, min_length=1, max_length=32)
    legal_name: Optional[str] = Field(None, max_length=200)
    contacts: List[ContactIn] = Field(default=[], max_length=50)
    billing_rate_cents: Optional[int] = Field(None, ge=0, le=10_000_000)
    notes: Optional[str] = Field(None, max_length=4000)


def _client_view(ctx: Ctx, c: m.Client) -> dict:
    brands = list(ctx.db.scalars(select(m.Brand).where(m.Brand.client_id == c.id).order_by(m.Brand.name)))
    missions = list(ctx.db.scalars(select(m.Mission).where(m.Mission.client_id == c.id)))
    contracts = list(ctx.db.scalars(select(m.ClientContract).where(m.ClientContract.client_id == c.id).order_by(m.ClientContract.start_date)))
    counts: Dict[str, int] = {}
    for x in missions:
        counts[x.status] = counts.get(x.status, 0) + 1
    return {**serialize(c), "brands": [{"code": b.code, "name": b.name, "billing_rate_cents": b.billing_rate_cents} for b in brands],
            "missions": counts, "contracts": [serialize(k) for k in contracts], "archived": c.archived_at is not None}


@router.get("/clients")
def clients(ctx: Ctx = Depends(require("referential.read"))):
    return [_client_view(ctx, c) for c in ctx.db.scalars(select(m.Client).order_by(m.Client.name))]


@router.post("/clients", status_code=201)
def create_client(body: ClientIn, ctx: Ctx = Depends(require("referential.write"))):
    code = (body.code or _slug(body.name, 32)).strip()
    if ctx.db.scalar(select(m.Client).where(m.Client.code == code)) is not None:
        raise HTTPException(409, f"Le client {code} existe déjà.")
    c = m.Client(tenant_id=ctx.tenant_id, code=code, name=body.name.strip(), legal_name=body.legal_name, contacts=[x.model_dump() for x in body.contacts],
                 billing_rate_cents=body.billing_rate_cents, notes=body.notes)
    ctx.db.add(c)
    ctx.db.flush()
    audit(ctx, "client.create", "client", c.id, {"name": c.name, "code": code})
    return _client_view(ctx, c)


@router.put("/clients/{cid}")
def update_client(cid: str, body: ClientIn, ctx: Ctx = Depends(require("referential.write"))):
    """Le code reste l'identifiant stable du client : seul le nom et les informations changent."""
    c = get_or_404(ctx, m.Client, cid)
    before = {"name": c.name, "billing_rate_cents": c.billing_rate_cents}
    c.name, c.legal_name, c.notes = body.name.strip(), body.legal_name, body.notes
    c.contacts, c.billing_rate_cents = [x.model_dump() for x in body.contacts], body.billing_rate_cents
    audit(ctx, "client.update", "client", c.id, {"before": before, "after": {"name": c.name, "billing_rate_cents": c.billing_rate_cents}})
    ctx.db.flush()
    return _client_view(ctx, c)


class ArchiveIn(S):
    archived: bool


@router.delete("/clients/{cid}", status_code=204)
def delete_client(cid: str, ctx: Ctx = Depends(require("referential.write"))):
    """Suppression d'un client sans mission (saisie erronée) ; sinon il s'archive pour conserver l'historique."""
    c = get_or_404(ctx, m.Client, cid)
    if ctx.db.scalar(select(m.Mission.id).where(m.Mission.client_id == c.id).limit(1)) is not None:
        raise HTTPException(409, "Ce client a des missions : archivez-le pour conserver l'historique.")
    audit(ctx, "client.delete", "client", c.id, {"name": c.name, "code": c.code})
    ctx.db.delete(c)


@router.post("/clients/{cid}/archive")
def archive_client(cid: str, body: ArchiveIn, ctx: Ctx = Depends(require("referential.write"))):
    """Archiver ne supprime rien : marques, missions et plannings passés restent consultables."""
    c = get_or_404(ctx, m.Client, cid)
    c.archived_at = datetime.now(timezone.utc) if body.archived else None
    audit(ctx, "client.archive" if body.archived else "client.unarchive", "client", c.id)
    ctx.db.flush()
    return _client_view(ctx, c)


class BrandLinkIn(S):
    client_id: Optional[uuid.UUID] = None
    billing_rate_cents: Optional[int] = Field(None, ge=0, le=10_000_000)


@router.put("/catalog/brands/{code}/client")
def link_brand(code: str, body: BrandLinkIn, ctx: Ctx = Depends(require("referential.write"))):
    b = ctx.db.scalar(select(m.Brand).where(m.Brand.code == code))
    if b is None:
        raise HTTPException(404, "Marque inconnue")
    if body.client_id is not None and ctx.db.get(m.Client, body.client_id) is None:
        raise HTTPException(422, "Client inconnu")
    b.client_id = body.client_id
    if "billing_rate_cents" in body.model_fields_set:  # relier une marque à un client n'efface jamais son tarif
        b.billing_rate_cents = body.billing_rate_cents
    audit(ctx, "brand.client_link", "brand", code, {"client_id": str(body.client_id) if body.client_id else None, "billing_rate_cents": b.billing_rate_cents})
    return {"code": b.code, "client_id": str(b.client_id) if b.client_id else None, "billing_rate_cents": b.billing_rate_cents}


class ContractIn(S):
    reference: str = Field(min_length=1, max_length=100)
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    ordered_minutes: Optional[int] = Field(None, ge=0)
    billing_rate_cents: Optional[int] = Field(None, ge=0, le=10_000_000)
    notes: Optional[str] = Field(None, max_length=2000)

    @model_validator(mode="after")
    def _d(self):
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("La fin du contrat précède son début.")
        return self


@router.post("/clients/{cid}/contracts", status_code=201)
def create_contract(cid: str, body: ContractIn, ctx: Ctx = Depends(require("referential.write"))):
    c = get_or_404(ctx, m.Client, cid)
    k = m.ClientContract(tenant_id=ctx.tenant_id, client_id=c.id, **body.model_dump())
    ctx.db.add(k)
    ctx.db.flush()
    audit(ctx, "client.contract_create", "client_contract", k.id, {"client": c.code, "reference": k.reference})
    return serialize(k)


@router.put("/client-contracts/{kid}")
def update_contract(kid: str, body: ContractIn, ctx: Ctx = Depends(require("referential.write"))):
    k = get_or_404(ctx, m.ClientContract, kid)
    for f, v in body.model_dump().items():
        setattr(k, f, v)
    audit(ctx, "client.contract_update", "client_contract", k.id, {"reference": k.reference})
    ctx.db.flush()
    return serialize(k)


@router.delete("/client-contracts/{kid}", status_code=204)
def delete_contract(kid: str, ctx: Ctx = Depends(require("referential.write"))):
    k = get_or_404(ctx, m.ClientContract, kid)
    audit(ctx, "client.contract_delete", "client_contract", k.id, {"reference": k.reference})
    ctx.db.delete(k)


# ---- missions ----
class MissionIn(S):
    client_id: uuid.UUID
    brand_code: str = Field(max_length=64)
    title: str = Field(min_length=1, max_length=200)
    site_codes: List[str] = Field(min_length=1, max_length=50)
    start_date: date
    end_date: date
    weekdays: List[int] = Field(min_length=1)
    start_time: time
    end_time: time
    break_minutes: int = Field(60, ge=0, le=240)
    headcount: int = Field(1, ge=1, le=200)
    required_skills: List[str] = Field(default=[], max_length=50)
    budget_minutes: Optional[int] = Field(None, ge=0)
    billing_rate_cents: Optional[int] = Field(None, ge=0, le=10_000_000)
    priority: int = Field(3, ge=1, le=5)
    notes: Optional[str] = Field(None, max_length=4000)

    @field_validator("weekdays")
    @classmethod
    def _wd(cls, v):
        if any(d < 0 or d > 6 for d in v):
            raise ValueError("Jours : 0 (lundi) à 6 (dimanche).")
        return sorted(set(v))

    @model_validator(mode="after")
    def _m(self):
        if self.end_date < self.start_date:
            raise ValueError("La fin de la mission précède son début.")
        if (self.end_date - self.start_date).days > 800:
            raise ValueError("Une mission dure au plus 800 jours.")
        if self.end_time <= self.start_time:
            raise ValueError("La fin du shift précède son début.")
        return self


def _check_refs(ctx: Ctx, body: MissionIn) -> None:
    if ctx.db.get(m.Client, body.client_id) is None:
        raise HTTPException(422, "Client inconnu")
    if ctx.db.scalar(select(m.Brand).where(m.Brand.code == body.brand_code)) is None:
        raise HTTPException(422, "Marque inconnue")
    sites = {s.code for s in ctx.db.scalars(select(m.Site))}
    missing = [x for x in body.site_codes if x not in sites]
    if missing:
        raise HTTPException(422, f"Site inconnu : {', '.join(missing)}")
    skills = {s.code for s in ctx.db.scalars(select(m.Skill))}
    missing = [x for x in body.required_skills if x not in skills]
    if missing:
        raise HTTPException(422, f"Qualification inconnue : {', '.join(missing)}")
    try:
        shift_hours(body.start_date, body.start_time, body.end_time, body.break_minutes)
    except ValueError as e:
        raise HTTPException(422, str(e))


def _days(x: m.Mission) -> List[date]:
    out, d = [], x.start_date
    while d <= x.end_date:
        if d.weekday() in (x.weekdays or []):
            out.append(d)
        d += timedelta(days=1)
    return out


def _req_code(x: m.Mission, site: str) -> str:
    return f"MSN-{x.code}-{_slug(site, 12)}-{x.start_time:%H%M}{x.end_time:%H%M}"


def _sync_requirements(ctx: Ctx, x: m.Mission) -> None:
    """Fait correspondre les besoins à la mission. Un changement d'horaire crée un autre code : les anciens shifts deviennent hors mission (signalés)."""
    existing = {r.code: r for r in ctx.db.scalars(select(m.StaffingRequirement).where(m.StaffingRequirement.mission_id == x.id))}
    wanted = {_req_code(x, s): s for s in x.site_codes}
    stale_templates = {r.template_id for r in existing.values()}
    for code, r in existing.items():
        if code not in wanted:
            ctx.db.delete(r)
    ctx.db.flush()
    for code, site in wanted.items():
        r = existing.get(code)
        tpl = ctx.db.get(m.ShiftTemplate, r.template_id) if r else None
        if tpl is None or (tpl.start_time, tpl.end_time, tpl.break_minutes) != (x.start_time, x.end_time, x.break_minutes):
            tpl = _template(ctx, site, x.brand_code, x.start_time, x.end_time, x.break_minutes)
        if r is None:
            r = m.StaffingRequirement(tenant_id=ctx.tenant_id, code=code, site_code=site, mission_id=x.id, template_id=tpl.id, allocations={x.brand_code: 1})
            ctx.db.add(r)
        r.template_id, r.allocations = tpl.id, {x.brand_code: 1}
        r.weekdays, r.dates, r.mandatory = list(x.weekdays), [], True
        r.required_skills, r.headcount, r.priority = list(x.required_skills or []), x.headcount, x.priority
        r.valid_from, r.valid_to = x.start_date, x.end_date
    ctx.db.flush()
    _drop_unused_templates(ctx, stale_templates)


def _drop_unused_templates(ctx: Ctx, ids: set) -> None:
    """Horaire créé pour une mission : retiré dès qu'aucun besoin ne l'utilise (aucun horaire orphelin)."""
    for tid in ids:
        t = ctx.db.get(m.ShiftTemplate, tid)
        if t is not None and t.scope_type == "pair" and ctx.db.scalar(select(m.StaffingRequirement.id).where(m.StaffingRequirement.template_id == tid).limit(1)) is None:
            ctx.db.delete(t)
    ctx.db.flush()


def _mission_shifts(ctx: Ctx, x: m.Mission) -> List[m.Shift]:
    return list(ctx.db.scalars(select(m.Shift).where(m.Shift.slot_key.like(f"MSN-{x.code}-%")).order_by(m.Shift.day)))


def _orphans(ctx: Ctx, x: m.Mission) -> List[m.Shift]:
    """Shifts déjà planifiés qui ne correspondent plus à la mission (annulée, dates, jours, sites ou horaires modifiés)."""
    valid_days = set(_days(x)) if x.status in PLANNED_MISSION_STATUSES else set()
    codes = {_req_code(x, s) for s in x.site_codes} if x.status in PLANNED_MISSION_STATUSES else set()
    return [sh for sh in _mission_shifts(ctx, x) if sh.day not in valid_days or sh.slot_key.split("|")[0].split("#")[0] not in codes]


def _mission_view(ctx: Ctx, x: m.Mission, client_names: Optional[dict] = None) -> dict:
    client_names = client_names if client_names is not None else {c.id: c.name for c in ctx.db.scalars(select(m.Client))}
    h = shift_hours(x.start_date, x.start_time, x.end_time, x.break_minutes)
    days = _days(x)
    needed = len(days) * max(1, len(x.site_codes or [])) * x.headcount
    shifts = _mission_shifts(ctx, x)
    ids = [s.id for s in shifts]
    assigned = set(ctx.db.scalars(select(m.Assignment.shift_id).where(m.Assignment.shift_id.in_(ids)))) if ids else set()
    return {**{k: v for k, v in serialize(x).items()}, "client_name": client_names.get(x.client_id, "—"), "days": len(days), "shifts_needed": needed,
            "minutes_needed": needed * h.effective_minutes, "effective_minutes_per_shift": h.effective_minutes, "shifts_generated": len(shifts), "shifts_assigned": len(assigned),
            "minutes_assigned": sum(s.effective_minutes for s in shifts if s.id in assigned)}


@router.get("/missions")
def missions(status: Optional[str] = None, client_id: Optional[uuid.UUID] = None, ctx: Ctx = Depends(require("referential.read"))):
    q = select(m.Mission).order_by(m.Mission.start_date.desc(), m.Mission.created_at.desc())
    if status:
        q = q.where(m.Mission.status == status)
    if client_id:
        q = q.where(m.Mission.client_id == client_id)
    names = {c.id: c.name for c in ctx.db.scalars(select(m.Client))}
    return [_mission_view(ctx, x, names) for x in ctx.db.scalars(q)]


@router.get("/missions/{mid}")
def mission(mid: str, ctx: Ctx = Depends(require("referential.read"))):
    return _mission_view(ctx, get_or_404(ctx, m.Mission, mid))


@router.post("/missions", status_code=201)
def create_mission(body: MissionIn, ctx: Ctx = Depends(require("referential.write"))):
    _check_refs(ctx, body)
    x = m.Mission(tenant_id=ctx.tenant_id, code=f"{_slug(body.brand_code, 10)}-{uuid.uuid4().hex[:6].upper()}", status="draft", **body.model_dump())
    ctx.db.add(x)
    ctx.db.flush()
    audit(ctx, "mission.create", "mission", x.id, {"code": x.code, "title": x.title, "brand": x.brand_code})
    return _mission_view(ctx, x)


def _impact(ctx: Ctx, x: m.Mission) -> dict:
    rows = _orphans(ctx, x)
    ids = [s.id for s in rows]
    assigned = {a.shift_id: a for a in ctx.db.scalars(select(m.Assignment).where(m.Assignment.shift_id.in_(ids)))} if ids else {}
    emps = {e.id: e.name for e in ctx.db.scalars(select(m.Employee))}
    return {"count": len(rows), "assigned": len(assigned),
            "shifts": [{"shift_id": str(s.id), "day": s.day.isoformat(), "site": s.site_code, "start": s.start_time.isoformat()[:5], "end": s.end_time.isoformat()[:5],
                        "employee": emps.get(assigned[s.id].employee_id) if s.id in assigned else None, "past": s.day < date.today()} for s in rows[:200]]}


@router.put("/missions/{mid}")
def update_mission(mid: str, body: MissionIn, ctx: Ctx = Depends(require("referential.write"))):
    """Modification d'une demande client. Une mission confirmée reste planifiable : ses besoins suivent, et les shifts déjà planifiés
    qui n'y correspondent plus sont renvoyés (`impact`), jamais supprimés sans action du manager."""
    x = get_or_404(ctx, m.Mission, mid)
    if x.status in ("cancelled", "completed"):
        raise HTTPException(409, "Cette mission est terminée ou annulée : renouvelez-la pour en créer une nouvelle.")
    _check_refs(ctx, body)
    before = {k: str(getattr(x, k)) for k in ("start_date", "end_date", "start_time", "end_time", "headcount", "priority")}
    for f, v in body.model_dump().items():
        setattr(x, f, v)
    if x.status == "confirmed":
        _sync_requirements(ctx, x)
    ctx.db.flush()
    audit(ctx, "mission.update", "mission", x.id, {"code": x.code, "before": before, "after": {k: str(getattr(x, k)) for k in before}})
    return {**_mission_view(ctx, x), "impact": _impact(ctx, x)}


def _eligibility(ctx: Ctx, x: m.Mission) -> dict:
    """Pour chaque collaborateur actif : marque, qualifications, sites et jours de disponibilité sur la mission (mêmes règles que le moteur)."""
    skills = {s.id: s for s in ctx.db.scalars(select(m.Skill))}
    owned: Dict[uuid.UUID, set] = {}
    for es in ctx.db.scalars(select(m.EmployeeSkill)):
        if es.valid_until is None or es.valid_until >= x.end_date:
            owned.setdefault(es.employee_id, set()).add(skills[es.skill_id].code)
    days = _days(x)
    unav: Dict[uuid.UUID, set] = {}
    wd: Dict[uuid.UUID, set] = {}
    for u in ctx.db.scalars(select(m.Unavailability)):
        if u.on_date is not None:
            unav.setdefault(u.employee_id, set()).add(u.on_date)
        elif u.weekday is not None:
            wd.setdefault(u.employee_id, set()).add(u.weekday)
    allowed: Dict[uuid.UUID, set] = {}
    for p in ctx.db.scalars(select(m.EmployeePreference).where(m.EmployeePreference.kind == "sites", m.EmployeePreference.is_hard.is_(True))):
        allowed.setdefault(p.employee_id, set()).update((p.params or {}).get("sites", []))
    rows = []
    for e in ctx.db.scalars(select(m.Employee).where(m.Employee.active.is_(True)).order_by(m.Employee.name)):
        lacking = [k for k in (x.required_skills or []) if k not in owned.get(e.id, set())]
        level = (e.brands or {}).get(x.brand_code)
        free = [d for d in days if d not in unav.get(e.id, set()) and d.weekday() not in wd.get(e.id, set())]
        sites_ok = [s for s in x.site_codes if e.id not in allowed or s in allowed[e.id]]
        reasons = []
        if level is None:
            reasons.append(f"{x.brand_code} n'est pas autorisée dans sa fiche")
        if lacking:
            reasons.append("Qualification manquante : " + ", ".join(lacking))
        if not sites_ok:
            reasons.append("Sites de la mission non autorisés")
        if not free:
            reasons.append("Indisponible sur toute la mission")
        rows.append({"employee_id": str(e.id), "name": e.name, "eligible": not reasons, "brand_level": level, "missing_skills": lacking,
                     "available_days": len(free), "total_days": len(days), "reasons": reasons})
    n = sum(1 for r in rows if r["eligible"])
    warn = None
    if n == 0:
        warn = "Aucun collaborateur admissible : la mission restera non couverte tant qu'aucun n'est autorisé ou qualifié."
    elif n < x.headcount:
        warn = f"{n} collaborateur(s) admissible(s) pour {x.headcount} personne(s) requise(s) chaque jour : couverture complète impossible."
    return {"eligible": n, "headcount": x.headcount, "warning": warn, "employees": sorted(rows, key=lambda r: (not r["eligible"], r["name"]))}


@router.get("/missions/{mid}/eligibility")
def eligibility(mid: str, ctx: Ctx = Depends(require("employees.read"))):
    return _eligibility(ctx, get_or_404(ctx, m.Mission, mid))


@router.post("/missions/{mid}/confirm")
def confirm(mid: str, ctx: Ctx = Depends(require("referential.write"))):
    """La mission entre dans la planification. Rien n'est généré automatiquement : le manager lance la génération ou la réoptimisation."""
    x = get_or_404(ctx, m.Mission, mid)
    if x.status not in ("draft",):
        raise HTTPException(409, "Seule une mission en brouillon peut être confirmée.")
    x.status = "confirmed"
    _sync_requirements(ctx, x)
    elig = _eligibility(ctx, x)
    audit(ctx, "mission.confirm", "mission", x.id, {"code": x.code, "eligible": elig["eligible"]})
    return {**_mission_view(ctx, x), "eligibility": {"eligible": elig["eligible"], "warning": elig["warning"]}}


class CancelIn(S):
    reason: Optional[str] = Field(None, max_length=300)
    release_shifts: bool = False  # retire aussi les shifts à venir déjà planifiés (décision explicite du manager)


def _release(ctx: Ctx, x: m.Mission) -> int:
    """Retire du planning les shifts à venir qui ne correspondent plus à la mission : le passé et les plannings archivés restent intacts."""
    today, removed = date.today(), 0
    archived = {p.id for p in ctx.db.scalars(select(m.PlanningPeriod).where(m.PlanningPeriod.archived_at.is_not(None)))}
    for sh in _orphans(ctx, x):
        if sh.day < today or sh.period_id in archived:
            continue
        a = ctx.db.scalar(select(m.Assignment).where(m.Assignment.shift_id == sh.id))
        if a is not None:
            who = ctx.db.get(m.Employee, a.employee_id)
            audit(ctx, "assignment.mission_release", "assignment", a.id, assignment_detail(ctx.db, sh, who, None, reason=f"Mission {x.code} : {x.title}"))
            ctx.db.delete(a)
        ctx.db.delete(sh)
        removed += 1
    ctx.db.flush()
    return removed


@router.post("/missions/{mid}/cancel")
def cancel(mid: str, body: CancelIn, ctx: Ctx = Depends(require("referential.write"))):
    x = get_or_404(ctx, m.Mission, mid)
    if x.status == "cancelled":
        raise HTTPException(409, "Cette mission est déjà annulée.")
    x.status, x.cancelled_reason = "cancelled", body.reason
    ctx.db.flush()
    removed = _release(ctx, x) if body.release_shifts else 0
    audit(ctx, "mission.cancel", "mission", x.id, {"code": x.code, "reason": body.reason, "released": removed})
    return {**_mission_view(ctx, x), "released": removed, "impact": _impact(ctx, x)}


@router.post("/missions/{mid}/release-shifts")
def release_shifts(mid: str, ctx: Ctx = Depends(require("planning.edit"))):
    x = get_or_404(ctx, m.Mission, mid)
    removed = _release(ctx, x)
    audit(ctx, "mission.release_shifts", "mission", x.id, {"code": x.code, "released": removed})
    return {"released": removed, "impact": _impact(ctx, x)}


@router.post("/missions/{mid}/complete")
def complete(mid: str, ctx: Ctx = Depends(require("referential.write"))):
    x = get_or_404(ctx, m.Mission, mid)
    if x.status != "confirmed":
        raise HTTPException(409, "Seule une mission confirmée peut être terminée.")
    x.status = "completed"
    audit(ctx, "mission.complete", "mission", x.id, {"code": x.code})
    return _mission_view(ctx, x)


class RenewIn(S):
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def _r(self):
        if self.end_date < self.start_date:
            raise ValueError("La fin de la mission précède son début.")
        return self


@router.post("/missions/{mid}/renew", status_code=201)
def renew(mid: str, body: RenewIn, ctx: Ctx = Depends(require("referential.write"))):
    """Renouvellement : une nouvelle mission en brouillon reprend la demande, l'ancienne reste dans l'historique."""
    o = get_or_404(ctx, m.Mission, mid)
    x = m.Mission(tenant_id=ctx.tenant_id, code=f"{_slug(o.brand_code, 10)}-{uuid.uuid4().hex[:6].upper()}", client_id=o.client_id, brand_code=o.brand_code, title=o.title,
                  site_codes=list(o.site_codes), start_date=body.start_date, end_date=body.end_date, weekdays=list(o.weekdays), start_time=o.start_time, end_time=o.end_time,
                  break_minutes=o.break_minutes, headcount=o.headcount, required_skills=list(o.required_skills or []), budget_minutes=o.budget_minutes,
                  billing_rate_cents=o.billing_rate_cents, priority=o.priority, notes=o.notes, status="draft", renewed_from=o.id)
    ctx.db.add(x)
    ctx.db.flush()
    audit(ctx, "mission.renew", "mission", x.id, {"code": x.code, "from": o.code})
    return _mission_view(ctx, x)


@router.delete("/missions/{mid}", status_code=204)
def delete_mission(mid: str, ctx: Ctx = Depends(require("referential.write"))):
    """Suppression d'un brouillon, ou d'une mission annulée qui n'a laissé aucun shift : rien de ce qui a été planifié n'est effacé."""
    x = get_or_404(ctx, m.Mission, mid)
    if x.status not in ("draft", "cancelled"):
        raise HTTPException(409, "Une mission confirmée s'annule d'abord : son historique est conservé.")
    if _mission_shifts(ctx, x):
        raise HTTPException(409, "Cette mission a des shifts dans un planning : son historique est conservé.")
    audit(ctx, "mission.delete", "mission", x.id, {"code": x.code, "title": x.title})
    templates = {r.template_id for r in ctx.db.scalars(select(m.StaffingRequirement).where(m.StaffingRequirement.mission_id == x.id))}
    ctx.db.delete(x)
    ctx.db.flush()
    _drop_unused_templates(ctx, templates)


# ---- qualifications et compétences (référentiel simple, utilisé par les fiches et les missions) ----
SkillCategory = Literal["competence", "formation", "langue", "certification", "qualification"]


class SkillIn(S):
    name: str = Field(min_length=1, max_length=200)
    code: Optional[str] = Field(None, min_length=1, max_length=64)
    category: SkillCategory = "competence"


@router.post("/skills/new", status_code=201)
def create_skill(body: SkillIn, ctx: Ctx = Depends(require("referential.write"))):
    code = (body.code or _slug(body.name, 64)).strip()
    if ctx.db.scalar(select(m.Skill).where(m.Skill.code == code)) is not None:
        raise HTTPException(409, f"La qualification {code} existe déjà.")
    s = m.Skill(tenant_id=ctx.tenant_id, code=code, name=body.name.strip(), category=body.category)
    ctx.db.add(s)
    ctx.db.flush()
    audit(ctx, "skill.create", "skill", s.id, {"code": code, "category": body.category})
    return serialize(s)


class EmployeeSkillsIn(S):
    skills: List[dict] = Field(max_length=200)  # [{code, valid_until?}]


@router.get("/employees/{eid}/skills")
def employee_skills(eid: str, ctx: Ctx = Depends(require("employees.read"))):
    e = get_or_404(ctx, m.Employee, eid)
    catalog = {s.id: s for s in ctx.db.scalars(select(m.Skill))}
    return [{"code": catalog[r.skill_id].code, "name": catalog[r.skill_id].name, "category": catalog[r.skill_id].category,
             "valid_until": r.valid_until.isoformat() if r.valid_until else None}
            for r in ctx.db.scalars(select(m.EmployeeSkill).where(m.EmployeeSkill.employee_id == e.id))]


@router.put("/employees/{eid}/skills")
def set_employee_skills(eid: str, body: EmployeeSkillsIn, ctx: Ctx = Depends(require("employees.write"))):
    """Remplace les qualifications du collaborateur. Le moteur n'affecte jamais une personne à un besoin dont il manque une qualification."""
    e = get_or_404(ctx, m.Employee, eid)
    catalog = {s.code: s for s in ctx.db.scalars(select(m.Skill))}
    wanted: Dict[str, Optional[date]] = {}
    for item in body.skills:
        code = item.get("code")
        if code not in catalog:
            raise HTTPException(422, f"Qualification inconnue : {code}")
        raw = item.get("valid_until")
        try:
            wanted[code] = date.fromisoformat(raw) if raw else None
        except (TypeError, ValueError):
            raise HTTPException(422, "Date d'échéance invalide")
    existing = {r.skill_id: r for r in ctx.db.scalars(select(m.EmployeeSkill).where(m.EmployeeSkill.employee_id == e.id))}
    keep = {catalog[c].id for c in wanted}
    for sid, r in existing.items():
        if sid not in keep:
            ctx.db.delete(r)
    for code, until in wanted.items():
        sid = catalog[code].id
        if sid in existing:
            existing[sid].valid_until = until
        else:
            ctx.db.add(m.EmployeeSkill(tenant_id=ctx.tenant_id, employee_id=e.id, skill_id=sid, valid_until=until))
    audit(ctx, "employee.skills", "employee", e.id, {"skills": sorted(wanted)})
    ctx.db.flush()
    return employee_skills(eid, ctx)
