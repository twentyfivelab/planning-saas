"""Sites et marques, entièrement configurables : sites, marques, « animations » (marque + site + horaire + jours + nombre de personnes).
Les codes sont des identifiants STABLES (référencés par les shifts) : renommer ne change que le nom affiché. Toute modification d'une
animation s'applique à partir d'un mois choisi ; les mois précédents conservent l'ancienne version (historique jamais réécrit)."""
import re
import unicodedata
import uuid
from datetime import date, time, timedelta
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select

from planning_solver.timecalc import shift_hours

from .. import models as m
from ..deps import Ctx, audit, get_or_404, require
from .months import parse_month

router = APIRouter(tags=["sites et marques"])
WD = ["lun", "mar", "mer", "jeu", "ven", "sam", "dim"]


def _slug(name: str, maxlen: int) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").upper()[:maxlen] or uuid.uuid4().hex[:6].upper()


def _in_month(r: m.StaffingRequirement, first: Optional[date]) -> bool:
    if first is None:
        return True
    last = (first.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    return (r.valid_from is None or r.valid_from <= last) and (r.valid_to is None or r.valid_to >= first)


@router.get("/catalog")
def catalog(month: Optional[str] = None, ctx: Ctx = Depends(require("referential.read"))):
    """Sites, marques et animations EN VIGUEUR pour le mois (ou toutes les versions sans mois)."""
    first = parse_month(month) if month else None
    templates = {t.id: t for t in ctx.db.scalars(select(m.ShiftTemplate))}
    uses: dict = {}
    for r in ctx.db.scalars(select(m.StaffingRequirement)):
        uses[r.template_id] = uses.get(r.template_id, 0) + 1
    brands = {b.code: b for b in ctx.db.scalars(select(m.Brand))}
    anim: dict = {}
    for r in ctx.db.scalars(select(m.StaffingRequirement).order_by(m.StaffingRequirement.code)):
        if not _in_month(r, first):
            continue
        t = templates[r.template_id]
        anim.setdefault(r.site_code, []).append({
            "id": str(r.id), "code": r.code, "brands": [{"code": b, "name": brands[b].name if b in brands else b} for b in r.allocations],
            "start": t.start_time.isoformat()[:5], "end": t.end_time.isoformat()[:5], "break_minutes": t.break_minutes,
            "weekdays": sorted(r.weekdays or []), "dates": r.dates or [], "headcount": r.headcount or 1, "mandatory": r.mandatory,
            "valid_from": r.valid_from.isoformat() if r.valid_from else None, "valid_to": r.valid_to.isoformat() if r.valid_to else None,
            "shared_schedule": uses.get(r.template_id, 0) > 1, "hypothesis": t.is_hypothesis})
    n_auth: dict = {}
    for e in ctx.db.scalars(select(m.Employee).where(m.Employee.active.is_(True), m.Employee.deleted_at.is_(None))):
        for b in (e.brands or {}):
            n_auth[b] = n_auth.get(b, 0) + 1
    sites = [{"code": s.code, "name": s.name, "archived_from": s.archived_from.isoformat() if s.archived_from else None,
              "archived": bool(s.archived_from and first and s.archived_from <= first),
              "animations": sorted(anim.get(s.code, []), key=lambda a: (a["brands"][0]["name"] if a["brands"] else "", a["start"]))}
             for s in ctx.db.scalars(select(m.Site).order_by(m.Site.name))]
    return {"month": first.isoformat() if first else None, "sites": sites,
            "brands": [{"code": b.code, "name": b.name, "group_code": b.group_code, "base_budget_minutes": b.base_budget_minutes, "archived_from": b.archived_from.isoformat() if b.archived_from else None,
                        "archived": bool(b.archived_from and first and b.archived_from <= first), "authorized_employees": n_auth.get(b.code, 0)}
                       for b in sorted(brands.values(), key=lambda x: (x.group_code or "~", x.name))]}


class SiteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    code: Optional[str] = Field(None, min_length=1, max_length=32)


@router.post("/catalog/sites", status_code=201)
def create_site(body: SiteIn, ctx: Ctx = Depends(require("referential.write"))):
    code = (body.code or _slug(body.name, 32)).strip()
    if ctx.db.scalar(select(m.Site).where(m.Site.code == code)) is not None:
        raise HTTPException(409, f"Le site {code} existe déjà.")
    s = m.Site(tenant_id=ctx.tenant_id, code=code, name=body.name.strip(), open_weekdays=[])
    ctx.db.add(s)
    ctx.db.flush()
    audit(ctx, "catalog.site_create", "site", s.id, {"code": code, "name": s.name})
    return {"code": s.code, "name": s.name}


class SitePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    archived_from: Optional[str] = None  # AAAA-MM ; "" = désarchiver


@router.patch("/catalog/sites/{code}")
def patch_site(code: str, body: SitePatch, ctx: Ctx = Depends(require("referential.write"))):
    """Renommer (le code reste identique : affectations et paramètres conservés) ou archiver à partir d'un mois (mois antérieurs intacts)."""
    s = ctx.db.scalar(select(m.Site).where(m.Site.code == code))
    if s is None:
        raise HTTPException(404, "Site inconnu")
    before = {"name": s.name, "archived_from": s.archived_from.isoformat() if s.archived_from else None}
    if body.name is not None:
        s.name = body.name.strip()
    if body.archived_from is not None:
        s.archived_from = parse_month(body.archived_from) if body.archived_from else None
    audit(ctx, "catalog.site_update", "site", s.id, {"code": code, "before": before, "after": body.model_dump(exclude_none=True)})
    return {"code": s.code, "name": s.name, "archived_from": s.archived_from.isoformat() if s.archived_from else None}


class BrandIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    group_code: Optional[str] = Field(None, max_length=64)
    base_budget_hours: Optional[float] = Field(None, ge=0, le=10000)  # budget de base par mois (heures de travail effectif)


@router.post("/catalog/brands", status_code=201)
def create_brand(body: BrandIn, ctx: Ctx = Depends(require("referential.write"))):
    code = body.name.strip()[:64]
    if ctx.db.scalar(select(m.Brand).where(m.Brand.code == code)) is not None:
        raise HTTPException(409, f"La marque {code} existe déjà.")
    b = m.Brand(tenant_id=ctx.tenant_id, code=code, name=body.name.strip(), group_code=(body.group_code or None), active_weekdays=[],
                base_budget_minutes=round(body.base_budget_hours * 60) if body.base_budget_hours is not None else None)
    ctx.db.add(b)
    ctx.db.flush()
    audit(ctx, "catalog.brand_create", "brand", b.id, {"code": code, "group": b.group_code, "base_budget_minutes": b.base_budget_minutes})
    return {"code": b.code, "name": b.name, "group_code": b.group_code, "base_budget_minutes": b.base_budget_minutes}


class BrandPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    group_code: Optional[str] = Field(None, max_length=64)
    archived_from: Optional[str] = None
    base_budget_hours: Optional[float] = Field(None, ge=0, le=10000)
    clear_base_budget: bool = False


@router.patch("/catalog/brands/{code}")
def patch_brand(code: str, body: BrandPatch, ctx: Ctx = Depends(require("referential.write"))):
    b = ctx.db.scalar(select(m.Brand).where(m.Brand.code == code))
    if b is None:
        raise HTTPException(404, "Marque inconnue")
    before = {"name": b.name, "group_code": b.group_code, "archived_from": b.archived_from.isoformat() if b.archived_from else None,
              "base_budget_minutes": b.base_budget_minutes}
    if body.clear_base_budget:
        b.base_budget_minutes = None
    elif body.base_budget_hours is not None:
        b.base_budget_minutes = round(body.base_budget_hours * 60)  # budget de base : les mois déjà créés ne changent pas
    if body.name is not None:
        b.name = body.name.strip()
    if body.group_code is not None:
        b.group_code = body.group_code or None
    if body.archived_from is not None:
        b.archived_from = parse_month(body.archived_from) if body.archived_from else None
    audit(ctx, "catalog.brand_update", "brand", b.id, {"code": code, "before": before, "after": body.model_dump(exclude_none=True)})
    return {"code": b.code, "name": b.name, "group_code": b.group_code, "base_budget_minutes": b.base_budget_minutes}


def _tag(start: time, end: time) -> str:
    return "close" if (end.hour + end.minute / 60) >= 20.5 else "open" if start.hour < 9 else "day"


def _hhmm(v: str) -> time:
    try:
        return time.fromisoformat(v)
    except ValueError:
        raise HTTPException(422, "Horaire invalide (HH:MM)")


class AnimationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    site_code: str = Field(max_length=32)
    brand_code: str = Field(max_length=64)
    start: str
    end: str
    break_minutes: int = Field(60, ge=0, le=240)
    weekdays: List[int] = Field(min_length=1)
    headcount: int = Field(1, ge=1, le=50)
    mandatory: bool = True
    from_month: str  # AAAA-MM : premier mois concerné

    @field_validator("weekdays")
    @classmethod
    def _wd(cls, v):
        if any(d < 0 or d > 6 for d in v):
            raise ValueError("jours : 0 (lundi) à 6 (dimanche)")
        return sorted(set(v))


def _template(ctx: Ctx, site: str, brand: str, start: time, end: time, brk: int) -> m.ShiftTemplate:
    """Horaire propre à la combinaison marque + site (portée « pair ») : jamais un horaire partagé modifié en silence."""
    code = f"{_slug(site, 12)}-{_slug(brand, 16)}-{start:%H%M}-{end:%H%M}-{uuid.uuid4().hex[:4]}"
    shift_hours(date(2026, 1, 5), start, end, brk)  # valide la durée (lève ValueError si incohérente)
    t = m.ShiftTemplate(tenant_id=ctx.tenant_id, code=code, start_time=start, end_time=end, break_minutes=brk, tag=_tag(start, end),
                        scope_type="pair", scope_code=f"{brand}@{site}")
    ctx.db.add(t)
    ctx.db.flush()
    return t


@router.post("/catalog/animations", status_code=201)
def create_animation(body: AnimationIn, ctx: Ctx = Depends(require("referential.write"))):
    """Nouvelle animation (marque sur un site, horaire, jours, nombre de personnes), en vigueur à partir de `from_month`."""
    if ctx.db.scalar(select(m.Site).where(m.Site.code == body.site_code)) is None:
        raise HTTPException(422, "Site inconnu")
    if ctx.db.scalar(select(m.Brand).where(m.Brand.code == body.brand_code)) is None:
        raise HTTPException(422, "Marque inconnue")
    first = parse_month(body.from_month)
    start, end = _hhmm(body.start), _hhmm(body.end)
    try:
        t = _template(ctx, body.site_code, body.brand_code, start, end, body.break_minutes)
    except ValueError as e:
        raise HTTPException(422, str(e))
    r = m.StaffingRequirement(tenant_id=ctx.tenant_id, code=f"{_slug(body.site_code, 12)}-{_slug(body.brand_code, 16)}-{start:%H%M}-{uuid.uuid4().hex[:6]}",
                              template_id=t.id, site_code=body.site_code, allocations={body.brand_code: 1}, weekdays=body.weekdays,
                              mandatory=body.mandatory, headcount=body.headcount, valid_from=first)
    ctx.db.add(r)
    ctx.db.flush()
    audit(ctx, "catalog.animation_create", "requirement", r.id, {"site": body.site_code, "brand": body.brand_code, "start": body.start, "end": body.end,
                                                                 "weekdays": body.weekdays, "headcount": body.headcount, "from": first.isoformat()})
    return {"id": str(r.id), "code": r.code}


class AnimationPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    from_month: str
    start: Optional[str] = None
    end: Optional[str] = None
    break_minutes: Optional[int] = Field(None, ge=0, le=240)
    weekdays: Optional[List[int]] = None
    headcount: Optional[int] = Field(None, ge=1, le=50)
    mandatory: Optional[bool] = None


def _version(ctx: Ctx, r: m.StaffingRequirement, first: date) -> m.StaffingRequirement:
    """Version du besoin à modifier à partir de `first` : la version en cours est close la veille et une copie démarre `first`
    (même code : les shifts déjà enregistrés des mois suivants restent rattachés)."""
    if r.valid_from is not None and r.valid_from >= first:
        return r
    if r.valid_to is not None and r.valid_to < first:
        raise HTTPException(422, "Cette version du besoin n'est plus en vigueur à partir de ce mois.")
    new = m.StaffingRequirement(tenant_id=ctx.tenant_id, code=r.code, template_id=r.template_id, site_code=r.site_code, allocations=dict(r.allocations),
                                weekdays=list(r.weekdays or []), dates=list(r.dates or []), mandatory=r.mandatory, flex_group=r.flex_group,
                                stagger_group=r.stagger_group, required_skills=list(r.required_skills or []), headcount=r.headcount or 1,
                                valid_from=first, valid_to=r.valid_to)
    r.valid_to = first - timedelta(days=1)
    ctx.db.add(new)
    ctx.db.flush()
    return new


@router.patch("/catalog/animations/{rid}")
def patch_animation(rid: str, body: AnimationPatch, ctx: Ctx = Depends(require("referential.write"))):
    """Modifie horaires, jours ou nombre de personnes À PARTIR d'un mois : les mois précédents gardent leur configuration."""
    r = get_or_404(ctx, m.StaffingRequirement, rid)
    first = parse_month(body.from_month)
    t = ctx.db.get(m.ShiftTemplate, r.template_id)
    before = {"start": t.start_time.isoformat()[:5], "end": t.end_time.isoformat()[:5], "weekdays": r.weekdays, "headcount": r.headcount, "mandatory": r.mandatory}
    v = _version(ctx, r, first)
    if body.start is not None or body.end is not None or body.break_minutes is not None:
        start = _hhmm(body.start) if body.start else t.start_time
        end = _hhmm(body.end) if body.end else t.end_time
        brk = body.break_minutes if body.break_minutes is not None else t.break_minutes
        brand = next(iter(v.allocations), "")
        try:
            v.template_id = _template(ctx, v.site_code, brand, start, end, brk).id
        except ValueError as e:
            raise HTTPException(422, str(e))
    if body.weekdays is not None:
        if not body.weekdays or any(d < 0 or d > 6 for d in body.weekdays):
            raise HTTPException(422, "Choisissez au moins un jour (0 = lundi … 6 = dimanche).")
        v.weekdays = sorted(set(body.weekdays))
    if body.headcount is not None:
        v.headcount = body.headcount
    if body.mandatory is not None:
        v.mandatory = body.mandatory
    ctx.db.flush()
    audit(ctx, "catalog.animation_update", "requirement", v.id, {"code": v.code, "from": first.isoformat(), "before": before,
                                                                 "after": body.model_dump(exclude_none=True, exclude={"from_month"})})
    return {"id": str(v.id), "code": v.code, "valid_from": v.valid_from.isoformat() if v.valid_from else None}


@router.delete("/catalog/animations/{rid}", status_code=204)
def end_animation(rid: str, from_month: str, ctx: Ctx = Depends(require("referential.write"))):
    """Arrête une animation à partir d'un mois (les mois précédents et leurs shifts sont conservés)."""
    r = get_or_404(ctx, m.StaffingRequirement, rid)
    first = parse_month(from_month)
    if r.valid_from is not None and r.valid_from >= first:
        audit(ctx, "catalog.animation_delete", "requirement", r.id, {"code": r.code, "from": first.isoformat()})
        tid = r.template_id
        ctx.db.delete(r)
        ctx.db.flush()
        t = ctx.db.get(m.ShiftTemplate, tid)  # horaire propre à cette animation (portée « pair ») : supprimé s'il ne sert plus
        if t is not None and t.scope_type == "pair" and ctx.db.scalar(select(m.StaffingRequirement.id).where(m.StaffingRequirement.template_id == tid).limit(1)) is None:
            ctx.db.delete(t)
    else:
        r.valid_to = first - timedelta(days=1)
        audit(ctx, "catalog.animation_end", "requirement", r.id, {"code": r.code, "until": r.valid_to.isoformat()})


class AuthorizeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    employee_ids: List[uuid.UUID] = Field(max_length=2000)
    level: Literal["priority", "secondary", "reinforce"] = "priority"


@router.post("/catalog/brands/{code}/authorize")
def authorize(code: str, body: AuthorizeIn, ctx: Ctx = Depends(require("employees.write"))):
    """Autorise des collaborateurs sur une marque (réglage permanent de leur fiche, comme la case « Marques et boutiques autorisées »)."""
    if ctx.db.scalar(select(m.Brand).where(m.Brand.code == code)) is None:
        raise HTTPException(404, "Marque inconnue")
    done = []
    for eid in body.employee_ids:
        e = ctx.db.get(m.Employee, eid)
        if e is None:
            raise HTTPException(422, "Collaborateur inconnu")
        if (e.brands or {}).get(code) != body.level:
            e.brands = {**(e.brands or {}), code: body.level}
            done.append(e.name)
    if done:
        audit(ctx, "catalog.brand_authorize", "brand", code, {"employees": done, "level": body.level})
    return {"authorized": done}
