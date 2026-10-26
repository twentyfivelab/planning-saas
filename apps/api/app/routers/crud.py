"""Référentiels du tenant : CRUD générique, validation stricte (Pydantic extra=forbid), RBAC et audit."""
import uuid
from datetime import date, time
from typing import List, Optional, Type

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .. import models as m
from ..deps import Ctx, audit, get_or_404, require


class S(BaseModel):
    model_config = ConfigDict(extra="forbid")


Weekday = Field(ge=0, le=6)


def _weekdays(v):
    if any((not isinstance(x, int)) or x < 0 or x > 6 for x in v):
        raise ValueError("jours 0 (lundi) à 6 (dimanche)")
    return v


class SiteIn(S):
    code: str = Field(min_length=1, max_length=32)
    name: str = Field(max_length=200)
    open_weekdays: List[int] = []
    _v = field_validator("open_weekdays")(_weekdays)


class BrandIn(S):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(max_length=200)
    active_weekdays: List[int] = []
    group_code: Optional[str] = Field(None, max_length=64)
    _v = field_validator("active_weekdays")(_weekdays)


class SkillIn(S):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(max_length=200)


class EmployeeIn(S):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(max_length=200)
    brands: dict = {}
    allocation_weight: float = Field(1.0, gt=0, le=5)
    active: bool = True

    @field_validator("brands")
    @classmethod
    def _b(cls, v):
        if any(x not in ("priority", "reinforce") for x in v.values()):
            raise ValueError("niveau: priority | reinforce")
        return v


class EmployeeSkillIn(S):
    employee_id: uuid.UUID
    skill_id: uuid.UUID


class ContractIn(S):
    employee_id: uuid.UUID
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    activity_rate: Optional[float] = Field(None, gt=0, le=1)
    weekly_minutes: Optional[int] = Field(None, ge=0, le=7 * 24 * 60)
    monthly_min_minutes: Optional[int] = Field(None, ge=0)
    monthly_target_minutes: Optional[int] = Field(None, ge=0)
    monthly_max_minutes: Optional[int] = Field(None, ge=0)
    weekly_max_minutes: Optional[int] = Field(None, ge=0)
    overtime_allowed: bool = False
    collective_agreement_limits: dict = {}

    @model_validator(mode="after")
    def _c(self):
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date < start_date")
        lo, hi = self.monthly_min_minutes, self.monthly_max_minutes
        if lo is not None and hi is not None and lo > hi:
            raise ValueError("minimum > maximum")
        return self


class AvailabilityIn(S):
    employee_id: uuid.UUID
    weekday: int = Weekday
    start_time: Optional[time] = None
    end_time: Optional[time] = None


class UnavailabilityIn(S):
    employee_id: uuid.UUID
    weekday: Optional[int] = Field(None, ge=0, le=6)
    on_date: Optional[date] = None
    reason: Optional[str] = Field(None, max_length=200)

    @model_validator(mode="after")
    def _u(self):
        if (self.weekday is None) == (self.on_date is None):
            raise ValueError("weekday XOR on_date")
        return self


class LeaveIn(S):
    employee_id: uuid.UUID
    start_date: date
    end_date: date
    kind: str = Field("leave", max_length=32)
    status: str = Field("pending", pattern="^(pending|approved|rejected)$")

    @model_validator(mode="after")
    def _l(self):
        if self.end_date < self.start_date:
            raise ValueError("end_date < start_date")
        return self


class TemplateIn(S):
    code: str = Field(min_length=1, max_length=64)
    site_id: Optional[uuid.UUID] = None
    start_time: time
    end_time: time
    break_minutes: int = Field(60, ge=0, le=480)
    tag: str = Field("day", pattern="^(open|day|mid|close)$")
    is_hypothesis: bool = False
    hypothesis_note: Optional[str] = Field(None, max_length=300)


class RequirementIn(S):
    code: str = Field(min_length=1, max_length=64)
    template_id: uuid.UUID
    site_code: str = Field(max_length=64)
    allocations: dict
    weekdays: List[int] = []
    dates: List[str] = []  # ISO AAAA-MM-JJ (JSONB)
    mandatory: bool = True
    flex_group: Optional[str] = Field(None, max_length=64)
    stagger_group: Optional[str] = Field(None, max_length=64)
    required_skills: List[str] = []
    _v = field_validator("weekdays")(_weekdays)

    @field_validator("dates")
    @classmethod
    def _d(cls, v):
        for x in v:
            date.fromisoformat(x)
        return v

    @field_validator("allocations")
    @classmethod
    def _a(cls, v):
        if not v or any((not isinstance(x, (int, float))) or x <= 0 for x in v.values()):
            raise ValueError("allocations {marque: part>0}")
        return v


class BudgetIn(S):
    brand_code: str = Field(max_length=64)
    month: date
    target_minutes: int = Field(ge=0)
    requirements_defined: bool = True


class PreferenceIn(S):
    employee_id: uuid.UUID
    kind: str = Field(pattern="^(latest_start|preferred_times|preferred_tags|weekly_rest_days)$")
    params: dict
    strength: int = Field(1, ge=1, le=5)
    is_hard: bool = False


class RelationshipIn(S):
    employee_id: uuid.UUID
    other_employee_id: uuid.UUID
    kind: str = Field("opposite_shifts", pattern="^opposite_shifts$")
    note: Optional[str] = Field(None, max_length=200)


class ConstraintIn(S):
    kind: str = Field(pattern="^(legal|exception|internal|preference)$")
    code: str = Field(max_length=64)
    scope: str = Field("tenant", pattern="^(tenant|employee)$")
    employee_id: Optional[uuid.UUID] = None
    params: dict = {}
    jurisdiction: Optional[str] = Field(None, max_length=64)
    valid_from: Optional[date] = None
    valid_to: Optional[date] = None
    version: int = Field(1, ge=1)
    enabled: bool = True
    exception_reason: Optional[str] = Field(None, max_length=1000)

    @model_validator(mode="after")
    def _c(self):
        if self.kind == "exception" and not (self.exception_reason or "").strip():
            raise ValueError("une dérogation exige un motif")
        if self.scope == "employee" and not self.employee_id:
            raise ValueError("employee_id requis")
        return self


_REFS = {"employee_id": m.Employee, "other_employee_id": m.Employee, "skill_id": m.Skill,
         "template_id": m.ShiftTemplate, "site_id": m.Site}


def _check_refs(ctx: Ctx, data: dict) -> None:
    """Une référence vers un autre tenant est invisible sous RLS -> rejetée (422)."""
    for k, mdl in _REFS.items():
        v = data.get(k)
        if v is not None and ctx.db.get(mdl, v) is None:
            raise HTTPException(422, f"{k}: référence inconnue")


def _constraint_extra(ctx: Ctx, data: dict) -> None:
    if data["kind"] == "exception":
        data["enabled_by"] = ctx.user.id  # qui a activé l'exception ; le motif est obligatoire (validateur)
    data["legal_review_status"] = "a_valider"


def serialize(o) -> dict:
    d = {c.name: getattr(o, c.name) for c in o.__table__.columns}
    return {k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in d.items()}


def crud(path: str, model: Type, schema: Type[S], read_perm: str, write_perm: str, tag: str,
         extra_on_create=None) -> APIRouter:
    r = APIRouter(prefix=f"/{path}", tags=[tag])

    @r.get("")
    def list_(ctx: Ctx = Depends(require(read_perm)), limit: int = 500, offset: int = 0):
        rows = ctx.db.scalars(select(model).order_by(model.created_at).limit(min(limit, 1000)).offset(offset)).all()
        return [serialize(o) for o in rows]

    @r.post("", status_code=201)
    def create(body: schema, ctx: Ctx = Depends(require(write_perm))):  # type: ignore[valid-type]
        data = body.model_dump()
        _check_refs(ctx, data)
        if extra_on_create:
            extra_on_create(ctx, data)
        obj = model(tenant_id=ctx.tenant_id, **data)
        ctx.db.add(obj)
        try:
            ctx.db.flush()
        except IntegrityError:
            raise HTTPException(409, "Doublon ou référence invalide")
        audit(ctx, f"{path}.create", path, obj.id)
        return serialize(obj)

    @r.put("/{id_}")
    def update(id_: str, body: schema, ctx: Ctx = Depends(require(write_perm))):  # type: ignore[valid-type]
        obj = get_or_404(ctx, model, id_)
        data = body.model_dump()
        _check_refs(ctx, data)
        for k, v in data.items():
            setattr(obj, k, v)
        try:
            ctx.db.flush()
        except IntegrityError:
            raise HTTPException(409, "Doublon ou référence invalide")
        audit(ctx, f"{path}.update", path, obj.id)
        return serialize(obj)

    @r.delete("/{id_}", status_code=204)
    def delete(id_: str, ctx: Ctx = Depends(require(write_perm))):
        obj = get_or_404(ctx, model, id_)
        ctx.db.delete(obj)
        audit(ctx, f"{path}.delete", path, id_)

    return r


def routers() -> List[APIRouter]:
    return [
        crud("sites", m.Site, SiteIn, "referential.read", "referential.write", "référentiels"),
        crud("brands", m.Brand, BrandIn, "referential.read", "referential.write", "référentiels"),
        crud("skills", m.Skill, SkillIn, "referential.read", "referential.write", "référentiels"),
        crud("employees", m.Employee, EmployeeIn, "employees.read", "employees.write", "collaborateurs"),
        crud("employee-skills", m.EmployeeSkill, EmployeeSkillIn, "employees.read", "employees.write",
             "collaborateurs"),
        crud("contracts", m.EmploymentContract, ContractIn, "employees.read", "contracts.write", "contrats"),
        crud("availabilities", m.Availability, AvailabilityIn, "employees.read", "availability.write",
             "disponibilités"),
        crud("unavailabilities", m.Unavailability, UnavailabilityIn, "employees.read", "availability.write",
             "disponibilités"),
        crud("leaves", m.LeaveRequest, LeaveIn, "employees.read", "availability.write", "disponibilités"),
        crud("shift-templates", m.ShiftTemplate, TemplateIn, "referential.read", "referential.write", "besoins"),
        crud("staffing-requirements", m.StaffingRequirement, RequirementIn, "referential.read",
             "referential.write", "besoins"),
        crud("budgets", m.MonthlyBudget, BudgetIn, "referential.read", "budgets.write", "budgets"),
        crud("employee-preferences", m.EmployeePreference, PreferenceIn, "employees.read", "rules.write",
             "règles"),
        crud("relationship-preferences", m.RelationshipPreference, RelationshipIn, "employees.read",
             "rules.write", "règles"),
        crud("constraints", m.ConstraintDefinition, ConstraintIn, "referential.read", "rules.write", "règles",
             extra_on_create=_constraint_extra),
    ]
