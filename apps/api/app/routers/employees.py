"""Collaborateurs : liste, fiche d'ajout (contrôle des doublons), identité, suppression et réintégration.

La suppression retire le collaborateur des PROCHAINES planifications (générations, listes de choix, effectif des mois à venir) ; ses
affectations, son historique et les versions des plannings existants sont conservés tels quels."""
import re
import unicodedata
import uuid
from datetime import date, datetime, timezone
from typing import Dict, List, Literal, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from planning_solver.model import fmt_minutes

from .. import models as m
from ..deps import Ctx, audit, get_or_404, require
from ..limits import days_settings_error
from ..rbac import has_permission
from ..services_bridge import tenant_cap
from .crud import EmployeeIn, serialize

router = APIRouter(tags=["collaborateurs"])

PERSONAL = ("birth_date", "address_street", "address_postal_code", "address_city", "address_country", "phone", "email")
LEVELS = ("priority", "secondary", "reinforce")
PHONE = re.compile(r"^[+0-9 ().\-/]{6,32}$")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _today() -> date:
    return datetime.now(ZoneInfo("Europe/Zurich")).date()


def _view(ctx: Ctx, e: m.Employee) -> dict:
    d = serialize(e)
    if not has_permission(ctx.user.role, "employees.write"):  # coordonnées personnelles : réservées aux rôles qui gèrent les fiches
        for k in PERSONAL:
            d.pop(k, None)
    return d


@router.get("/employees")
def list_employees(include_deleted: bool = False, ctx: Ctx = Depends(require("employees.read"))):
    """Collaborateurs de l'équipe. `include_deleted=true` ajoute les collaborateurs supprimés (affichage de l'historique)."""
    q = select(m.Employee).order_by(m.Employee.created_at)
    if not include_deleted:
        q = q.where(m.Employee.deleted_at.is_(None))
    return [_view(ctx, e) for e in ctx.db.scalars(q)]


def _norm(s: Optional[str]) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r"[\s\-']+", " ", s).strip()


def _digits(p: Optional[str]) -> str:
    d = re.sub(r"\D", "", p or "")
    return d[-9:] if len(d) >= 9 else d


def _split(e: m.Employee):
    if e.first_name or e.last_name:
        return _norm(e.first_name), _norm(e.last_name)
    parts = _norm(e.name).split(" ")
    return parts[0], " ".join(parts[1:])


def find_duplicates(ctx: Ctx, first: str, last: str, email: Optional[str], phone: Optional[str], birth: Optional[date],
                    exclude: Optional[uuid.UUID] = None) -> List[dict]:
    """Fiches existantes (supprimées comprises) qui pourraient désigner la même personne, avec la raison.
    strong = même e-mail ou même téléphone (ajout refusé) ; sinon homonyme ou fiche au seul prénom (confirmation demandée)."""
    f, l = _norm(first), _norm(last)
    out = []
    for e in ctx.db.scalars(select(m.Employee)):
        if exclude is not None and e.id == exclude:
            continue
        reasons, strong = [], False
        if email and e.email and e.email.strip().lower() == email.strip().lower():
            reasons.append("même adresse e-mail")
            strong = True
        if phone and e.phone and _digits(e.phone) and _digits(e.phone) == _digits(phone):
            reasons.append("même numéro de téléphone")
            strong = True
        ef, el = _split(e)
        differ_birth = bool(birth and e.birth_date and birth != e.birth_date)
        if not differ_birth:
            if ef == f and el == l:
                reasons.append("même prénom et même nom")
            elif ef == f and not el:
                reasons.append(f"fiche enregistrée sous le seul prénom « {e.name} »")
            elif ef == f and el and l and (l.startswith(el) or el.startswith(l)) and min(len(el), len(l)) <= 2:
                reasons.append(f"fiche enregistrée avec une initiale (« {e.name} »)")
            elif el == l and l and ef and f and (ef.startswith(f) or f.startswith(ef)):
                reasons.append(f"même nom, prénom proche (« {e.name} »)")
        if reasons:
            out.append({"id": str(e.id), "name": e.name, "reasons": reasons, "strong": strong, "deleted": e.deleted_at is not None})
    return out


Weekdays = List[int]


def _wd(v):
    if any(not isinstance(x, int) or x < 0 or x > 6 for x in v):
        raise ValueError("jours 0 (lundi) à 6 (dimanche)")
    return sorted(set(v))


class Identity(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    birth_date: Optional[date] = None
    address_street: Optional[str] = Field(None, max_length=200)
    address_postal_code: Optional[str] = Field(None, max_length=16)
    address_city: Optional[str] = Field(None, max_length=100)
    address_country: Optional[str] = Field(None, max_length=100)
    phone: Optional[str] = Field(None, max_length=32)
    email: Optional[str] = Field(None, max_length=200)

    @model_validator(mode="after")
    def _check(self):
        for k in ("address_street", "address_postal_code", "address_city", "address_country", "phone", "email"):
            if getattr(self, k) == "":
                setattr(self, k, None)
        if self.phone and not PHONE.match(self.phone):
            raise ValueError("Numéro de téléphone invalide (chiffres, espaces, +, points ou tirets).")
        if self.email and not EMAIL.match(self.email):
            raise ValueError("Adresse e-mail invalide.")
        if self.birth_date and not (date(1900, 1, 1) <= self.birth_date <= _today()):
            raise ValueError("Date de naissance invalide.")
        return self


class OnboardIn(Identity):
    monthly_hours: Optional[float] = Field(None, ge=0, le=744)  # volume horaire contractuel par mois (objectif)
    weekly_hours: Optional[float] = Field(None, ge=0, le=168)
    brands: Dict[str, Literal["priority", "secondary", "reinforce"]] = {}
    sites: List[str] = Field(default=[], max_length=200)  # sites autorisés (vide = tous les sites de ses marques)
    available_weekdays: Weekdays = []  # vide = non déclaré (tous les jours)
    unavailable_weekdays: Weekdays = []
    unavailable_dates: List[date] = Field(default=[], max_length=400)
    time_pref: Optional[Literal["matin", "middle", "soir"]] = None
    time_pref_strict: bool = False
    min_days_month: Optional[int] = Field(None, ge=1, le=31)
    max_days_month: Optional[int] = Field(None, ge=1, le=31)
    confirm_duplicate: bool = False  # homonyme signalé : l'utilisateur confirme qu'il s'agit d'une autre personne
    _w1 = field_validator("available_weekdays")(_wd)
    _w2 = field_validator("unavailable_weekdays")(_wd)


def _code(ctx: Ctx, first: str, last: str) -> str:
    def slug(s: str) -> str:
        return re.sub(r"[^a-z0-9]+", "-", _norm(s)).strip("-")[:40] or "collaborateur"
    taken = set(ctx.db.scalars(select(m.Employee.code)))
    for c in (slug(first), f"{slug(first)}-{slug(last)}"):
        if c not in taken:
            return c
    n = 2
    while f"{slug(first)}-{slug(last)}-{n}" in taken:
        n += 1
    return f"{slug(first)}-{slug(last)}-{n}"


def _check_planning(ctx: Ctx, brands: dict, min_d: Optional[int], max_d: Optional[int], monthly_minutes: Optional[int]) -> None:
    err = days_settings_error(ctx.db, ctx.tenant_id, brands, min_d, max_d)
    if err:
        raise HTTPException(422, err)
    cap = tenant_cap(ctx.db, ctx.tenant_id)
    if cap is not None and monthly_minutes is not None and monthly_minutes > cap:
        raise HTTPException(422, f"Le volume contractuel ({fmt_minutes(monthly_minutes)} par mois) dépasse le plafond mensuel de {fmt_minutes(cap)} : "
                                 "le moteur ne pourrait jamais l'atteindre. Réduisez le volume ou faites modifier le plafond.")


@router.post("/employees/onboard", status_code=201)
def onboard(body: OnboardIn, ctx: Ctx = Depends(require("employees.write"))):
    """Fiche d'ajout complète, enregistrée en UNE transaction (tout ou rien) après contrôle des doublons."""
    dups = find_duplicates(ctx, body.first_name, body.last_name, body.email, body.phone, body.birth_date)
    strong = [d for d in dups if d["strong"]]
    if strong or (dups and not body.confirm_duplicate):
        first = (strong or dups)[0]
        hint = " Ce collaborateur a été supprimé : réintégrez-le plutôt que de créer une nouvelle fiche." if first["deleted"] else ""
        raise HTTPException(409, detail={"code": "duplicate", "can_confirm": not strong, "matches": dups,
                                         "message": f"Doublon possible avec {first['name']} ({', '.join(first['reasons'])}).{hint}"})
    known_brands = set(ctx.db.scalars(select(m.Brand.code)))
    unknown = sorted(b for b in body.brands if b not in known_brands)
    if unknown:
        raise HTTPException(422, f"Marque(s) inconnue(s) : {', '.join(unknown)}.")
    known_sites = set(ctx.db.scalars(select(m.Site.code)))
    if any(s not in known_sites for s in body.sites):
        raise HTTPException(422, f"Site(s) inconnu(s) : {', '.join(s for s in body.sites if s not in known_sites)}.")
    both = set(body.available_weekdays) & set(body.unavailable_weekdays)
    if both:
        days = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
        raise HTTPException(422, f"{', '.join(days[d] for d in sorted(both)).capitalize()} : à la fois disponible et indisponible.")
    if body.time_pref_strict and body.time_pref is None:
        raise HTTPException(422, "Une préférence horaire obligatoire exige une préférence choisie.")
    monthly = round(body.monthly_hours * 60) if body.monthly_hours is not None else None
    _check_planning(ctx, dict(body.brands), body.min_days_month, body.max_days_month, monthly)
    name = f"{body.first_name} {body.last_name}"
    e = m.Employee(tenant_id=ctx.tenant_id, code=_code(ctx, body.first_name, body.last_name), name=name, brands=dict(body.brands),
                   first_name=body.first_name, last_name=body.last_name, birth_date=body.birth_date, address_street=body.address_street,
                   address_postal_code=body.address_postal_code, address_city=body.address_city, address_country=body.address_country,
                   phone=body.phone, email=body.email, time_pref=body.time_pref, time_pref_strict=body.time_pref_strict,
                   min_days_month=body.min_days_month, max_days_month=body.max_days_month, sunday_quota_migrated_at=datetime.now(timezone.utc))
    ctx.db.add(e)
    try:
        ctx.db.flush()
    except IntegrityError:
        raise HTTPException(409, "Un collaborateur porte déjà cet identifiant : réessayez.")
    if monthly is not None or body.weekly_hours is not None:
        ctx.db.add(m.EmploymentContract(tenant_id=ctx.tenant_id, employee_id=e.id, monthly_target_minutes=monthly,
                                        weekly_minutes=round(body.weekly_hours * 60) if body.weekly_hours is not None else None))
    for wd in body.available_weekdays:
        ctx.db.add(m.Availability(tenant_id=ctx.tenant_id, employee_id=e.id, weekday=wd))
    for wd in body.unavailable_weekdays:
        ctx.db.add(m.Unavailability(tenant_id=ctx.tenant_id, employee_id=e.id, weekday=wd, reason="fiche d'ajout"))
    for d in sorted(set(body.unavailable_dates)):
        ctx.db.add(m.Unavailability(tenant_id=ctx.tenant_id, employee_id=e.id, on_date=d, reason="fiche d'ajout"))
    if body.sites:
        ctx.db.add(m.EmployeePreference(tenant_id=ctx.tenant_id, employee_id=e.id, kind="sites", is_hard=True, strength=1,
                                        params={"sites": sorted(set(body.sites))}))
    ctx.db.flush()
    audit(ctx, "employee.onboard", "employee", e.id, {"name": name, "duplicates_confirmed": [d["name"] for d in dups]})
    return {"id": str(e.id), "code": e.code, "name": name, "message": f"Le collaborateur {name} a été ajouté avec succès."}


@router.get("/employees/{eid}/identity")
def identity(eid: str, ctx: Ctx = Depends(require("employees.write"))):
    e = get_or_404(ctx, m.Employee, eid)
    # prénom et nom jamais déduits du nom affiché : vides tant qu'ils n'ont pas été saisis (répartition parfois incertaine)
    return {"id": str(e.id), "name": e.name, "first_name": e.first_name, "last_name": e.last_name,
            "split_unknown": not (e.first_name or e.last_name), **{k: getattr(e, k) for k in PERSONAL}}


@router.put("/employees/{eid}/identity")
def set_identity(eid: str, body: Identity, ctx: Ctx = Depends(require("employees.write"))):
    """Nom, prénom et coordonnées ; le nom affiché devient « Prénom Nom ». Contrôle des doublons (e-mail, téléphone)."""
    e = get_or_404(ctx, m.Employee, eid)
    strong = [d for d in find_duplicates(ctx, body.first_name, body.last_name, body.email, body.phone, body.birth_date, exclude=e.id) if d["strong"]]
    if strong:
        raise HTTPException(409, detail={"code": "duplicate", "can_confirm": False, "matches": strong,
                                         "message": f"Doublon : {strong[0]['name']} a déjà {', '.join(strong[0]['reasons'])}."})
    before = e.name
    for k, v in body.model_dump().items():
        setattr(e, k, v)
    e.name = f"{body.first_name} {body.last_name}"
    ctx.db.flush()
    audit(ctx, "employee.identity", "employee", e.id, {"before": before, "after": e.name})
    return _view(ctx, e)


@router.post("/employees", status_code=201)
def create_employee(body: EmployeeIn, ctx: Ctx = Depends(require("employees.write"))):
    """Création simple (API, import). La fiche d'ajout complète passe par POST /employees/onboard."""
    data = body.model_dump()
    _check_planning(ctx, data.get("brands") or {}, data.get("min_days_month"), data.get("max_days_month"), None)
    e = m.Employee(tenant_id=ctx.tenant_id, **data)
    ctx.db.add(e)
    try:
        ctx.db.flush()
    except IntegrityError:
        raise HTTPException(409, "Doublon ou référence invalide")
    audit(ctx, "employees.create", "employees", e.id)
    return _view(ctx, e)


@router.put("/employees/{eid}")
def update_employee(eid: str, body: EmployeeIn, ctx: Ctx = Depends(require("employees.write"))):
    """Mise à jour des champs ENVOYÉS uniquement (un champ absent n'est jamais remis à zéro)."""
    e = get_or_404(ctx, m.Employee, eid)
    data = body.model_dump(exclude_unset=True)
    min_d = data.get("min_days_month", e.min_days_month)
    max_d = data.get("max_days_month", e.max_days_month)
    if {"min_days_month", "max_days_month", "brands"} & set(data):
        _check_planning(ctx, data.get("brands", e.brands) or {}, min_d, max_d, None)
    for k, v in data.items():
        setattr(e, k, v)
    try:
        ctx.db.flush()
    except IntegrityError:
        raise HTTPException(409, "Doublon ou référence invalide")
    audit(ctx, "employees.update", "employees", e.id)
    return _view(ctx, e)


def _upcoming(ctx: Ctx, e: m.Employee, since: date) -> List[dict]:
    rows = ctx.db.execute(select(m.PlanningPeriod.name, func.count()).join(m.Assignment, m.Assignment.period_id == m.PlanningPeriod.id)
                          .join(m.Shift, m.Shift.id == m.Assignment.shift_id)
                          .where(m.Assignment.employee_id == e.id, m.Shift.day >= since)
                          .group_by(m.PlanningPeriod.name, m.PlanningPeriod.start_date).order_by(m.PlanningPeriod.start_date)).all()
    return [{"period": n, "assignments": c} for n, c in rows]


@router.get("/employees/{eid}/deletion-preview")
def deletion_preview(eid: str, ctx: Ctx = Depends(require("employees.write"))):
    """Ce que la suppression implique : affectations à venir dans les plannings existants (conservées, à réattribuer)."""
    e = get_or_404(ctx, m.Employee, eid)
    return {"name": e.name, "removed_on": _today().isoformat(), "upcoming": _upcoming(ctx, e, _today())}


@router.delete("/employees/{eid}")
def delete_employee(eid: str, ctx: Ctx = Depends(require("employees.write"))):
    """Suppression : le collaborateur n'est plus proposé ni planifié à partir d'aujourd'hui. Ses affectations et son historique restent."""
    e = get_or_404(ctx, m.Employee, eid)
    if e.deleted_at is not None:
        raise HTTPException(409, f"{e.name} a déjà été supprimé·e.")
    e.deleted_at, e.deleted_by, e.removed_on = datetime.now(timezone.utc), ctx.user.id, _today()
    up = _upcoming(ctx, e, e.removed_on)
    ctx.db.flush()
    audit(ctx, "employee.delete", "employee", e.id, {"name": e.name, "removed_on": e.removed_on.isoformat(), "upcoming": up})
    return {"id": str(e.id), "name": e.name, "removed_on": e.removed_on.isoformat(), "upcoming": up,
            "message": f"Le collaborateur {e.name} a été supprimé avec succès."}


@router.post("/employees/{eid}/restore")
def restore_employee(eid: str, ctx: Ctx = Depends(require("employees.write"))):
    """Réintégration d'un collaborateur supprimé : il redevient planifiable ; rien d'autre ne change."""
    e = get_or_404(ctx, m.Employee, eid)
    if e.deleted_at is None:
        raise HTTPException(409, f"{e.name} fait déjà partie de l'équipe.")
    before = e.removed_on.isoformat() if e.removed_on else None
    e.deleted_at, e.deleted_by, e.removed_on = None, None, None
    ctx.db.flush()
    audit(ctx, "employee.restore", "employee", e.id, {"name": e.name, "removed_on": before})
    return {**_view(ctx, e), "message": f"Le collaborateur {e.name} a été réintégré."}


class CapIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hours: Optional[float] = Field(None, gt=0, le=744)  # None = aucun plafond


@router.get("/settings/monthly-cap")
def get_monthly_cap(ctx: Ctx = Depends(require("planning.read"))):
    """Plafond mensuel d'heures de l'entreprise (règle interne, pas une valeur légale)."""
    cap = tenant_cap(ctx.db, ctx.tenant_id)
    return {"minutes": cap, "label": fmt_minutes(cap) if cap is not None else None,
            "scope": "travail effectif par collaborateur et par mois civil, tous sites et toutes marques cumulés"}


@router.put("/settings/monthly-cap")
def set_monthly_cap(body: CapIn, ctx: Ctx = Depends(require("tenant.manage"))):
    """Modifie le plafond pour les prochaines générations et modifications manuelles ; les plannings existants gardent le leur."""
    t = ctx.db.get(m.Tenant, ctx.tenant_id)
    before = t.monthly_hours_cap_minutes
    t.monthly_hours_cap_minutes = round(body.hours * 60) if body.hours is not None else None
    ctx.db.flush()
    audit(ctx, "settings.monthly_cap", "tenant", t.id, {"before": before, "after": t.monthly_hours_cap_minutes})
    return get_monthly_cap(ctx)
