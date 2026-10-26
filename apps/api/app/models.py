"""Modèle normalisé. Toutes les tables métier portent tenant_id (+ RLS, voir migration)."""
import uuid
from datetime import date, datetime, time
from typing import Any, Optional

from sqlalchemy import (Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, Time, UniqueConstraint,
                        func)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

PK = dict(primary_key=True, default=uuid.uuid4)


class Base(DeclarativeBase):
    pass


def tenant_fk():
    return mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True)


class TenantOwned:
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **PK)
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ---- globaux (pas de RLS) ----
class Role(Base):
    __tablename__ = "roles"
    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    label: Mapped[str] = mapped_column(String(100))


class Permission(Base):
    __tablename__ = "permissions"
    code: Mapped[str] = mapped_column(String(64), primary_key=True)


class RolePermission(Base):
    __tablename__ = "role_permissions"
    role: Mapped[str] = mapped_column(ForeignKey("roles.code"), primary_key=True)
    permission: Mapped[str] = mapped_column(ForeignKey("permissions.code"), primary_key=True)


class Session_(Base):
    __tablename__ = "sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    csrf_token: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ---- tenant ----
class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **PK)
    name: Mapped[str] = mapped_column(String(200))
    country: Mapped[str] = mapped_column(String(2), default="CH")
    canton: Mapped[Optional[str]] = mapped_column(String(4))
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Zurich")
    locale: Mapped[str] = mapped_column(String(8), default="fr")
    retention_months: Mapped[int] = mapped_column(Integer, default=24)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Subscription(TenantOwned, Base):  # préparation facturation, sans prestataire
    __tablename__ = "subscriptions"
    plan: Mapped[str] = mapped_column(String(32), default="trial")
    status: Mapped[str] = mapped_column(String(32), default="active")
    seats: Mapped[Optional[int]] = mapped_column(Integer)
    external_ref: Mapped[Optional[str]] = mapped_column(String(100))


class User(TenantOwned, Base):
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(String(254), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(300))
    role: Mapped[str] = mapped_column(ForeignKey("roles.code"))
    employee_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)


class Site(TenantOwned, Base):
    __tablename__ = "sites"
    code: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(200))
    open_weekdays: Mapped[Any] = mapped_column(JSONB, default=list)
    __table_args__ = (UniqueConstraint("tenant_id", "code"),)


class Brand(TenantOwned, Base):
    __tablename__ = "brands"
    code: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(200))
    active_weekdays: Mapped[Any] = mapped_column(JSONB, default=list)  # jours de fonctionnement
    group_code: Mapped[Optional[str]] = mapped_column(String(64))  # ex. COSMETIQUE
    __table_args__ = (UniqueConstraint("tenant_id", "code"),)


class Skill(TenantOwned, Base):
    __tablename__ = "skills"
    code: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(200))
    __table_args__ = (UniqueConstraint("tenant_id", "code"),)


class Employee(TenantOwned, Base):
    __tablename__ = "employees"
    code: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(200))
    brands: Mapped[Any] = mapped_column(JSONB, default=dict)  # {brand_code: priority|reinforce}
    allocation_weight: Mapped[float] = mapped_column(Float, default=1.0)  # préférence souple
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (UniqueConstraint("tenant_id", "code"),)


class EmployeeSkill(TenantOwned, Base):
    __tablename__ = "employee_skills"
    employee_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"))
    skill_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("skills.id", ondelete="CASCADE"))


class EmploymentContract(TenantOwned, Base):
    """Uniquement des valeurs saisies ; NULL = non renseigné."""
    __tablename__ = "employment_contracts"
    employee_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"))
    start_date: Mapped[Optional[date]] = mapped_column(Date)
    end_date: Mapped[Optional[date]] = mapped_column(Date)
    activity_rate: Mapped[Optional[float]] = mapped_column(Float)
    weekly_minutes: Mapped[Optional[int]] = mapped_column(Integer)
    monthly_min_minutes: Mapped[Optional[int]] = mapped_column(Integer)
    monthly_target_minutes: Mapped[Optional[int]] = mapped_column(Integer)
    monthly_max_minutes: Mapped[Optional[int]] = mapped_column(Integer)
    weekly_max_minutes: Mapped[Optional[int]] = mapped_column(Integer)
    overtime_allowed: Mapped[bool] = mapped_column(Boolean, default=False)
    collective_agreement_limits: Mapped[Any] = mapped_column(JSONB, default=dict)


class Availability(TenantOwned, Base):
    __tablename__ = "availabilities"
    employee_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"))
    weekday: Mapped[int] = mapped_column(Integer)
    start_time: Mapped[Optional[time]] = mapped_column(Time)
    end_time: Mapped[Optional[time]] = mapped_column(Time)


class Unavailability(TenantOwned, Base):
    __tablename__ = "unavailabilities"
    employee_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"))
    weekday: Mapped[Optional[int]] = mapped_column(Integer)  # récurrent
    on_date: Mapped[Optional[date]] = mapped_column(Date)
    reason: Mapped[Optional[str]] = mapped_column(String(200))


class LeaveRequest(TenantOwned, Base):
    __tablename__ = "leave_requests"
    employee_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    kind: Mapped[str] = mapped_column(String(32), default="leave")
    status: Mapped[str] = mapped_column(String(16), default="pending")


class ShiftTemplate(TenantOwned, Base):
    __tablename__ = "shift_templates"
    code: Mapped[str] = mapped_column(String(64))
    site_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("sites.id"))
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)
    break_minutes: Mapped[int] = mapped_column(Integer, default=60)
    tag: Mapped[str] = mapped_column(String(16), default="day")
    # horaire supposé, non fourni par le client : signalé comme hypothèse non validée partout (alertes, exports)
    is_hypothesis: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    hypothesis_note: Mapped[Optional[str]] = mapped_column(String(300))
    __table_args__ = (UniqueConstraint("tenant_id", "code"),)


class StaffingRequirement(TenantOwned, Base):
    """Besoin : un modèle de shift sur des jours (weekdays) ou dates, avec imputation aux marques."""
    __tablename__ = "staffing_requirements"
    code: Mapped[str] = mapped_column(String(64))
    template_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shift_templates.id"))
    site_code: Mapped[str] = mapped_column(String(64))
    allocations: Mapped[Any] = mapped_column(JSONB)  # {brand_code: part}
    weekdays: Mapped[Any] = mapped_column(JSONB, default=list)
    dates: Mapped[Any] = mapped_column(JSONB, default=list)  # ISO ; si non vide, prioritaire sur weekdays
    mandatory: Mapped[bool] = mapped_column(Boolean, default=True)
    flex_group: Mapped[Optional[str]] = mapped_column(String(64))  # 1 seul modèle par jour (shifts optionnels)
    stagger_group: Mapped[Optional[str]] = mapped_column(String(64))
    required_skills: Mapped[Any] = mapped_column(JSONB, default=list)


class MonthlyBudget(TenantOwned, Base):
    __tablename__ = "monthly_budgets"
    brand_code: Mapped[str] = mapped_column(String(64))
    month: Mapped[date] = mapped_column(Date)  # 1er du mois
    target_minutes: Mapped[int] = mapped_column(Integer)  # travail effectif
    requirements_defined: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (UniqueConstraint("tenant_id", "brand_code", "month"),)


class PlanningPeriod(TenantOwned, Base):
    __tablename__ = "planning_periods"
    name: Mapped[str] = mapped_column(String(100))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)


class Shift(TenantOwned, Base):
    """Shift planifié (présence). Une affectation = 1 personne."""
    __tablename__ = "shifts"
    period_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("planning_periods.id", ondelete="CASCADE"))
    slot_key: Mapped[str] = mapped_column(String(128))
    day: Mapped[date] = mapped_column(Date)
    site_code: Mapped[str] = mapped_column(String(64))
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)
    break_minutes: Mapped[int] = mapped_column(Integer)
    presence_minutes: Mapped[int] = mapped_column(Integer)
    effective_minutes: Mapped[int] = mapped_column(Integer)


class Assignment(TenantOwned, Base):
    __tablename__ = "assignments"
    period_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("planning_periods.id", ondelete="CASCADE"))
    shift_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shifts.id", ondelete="CASCADE"))
    employee_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("employees.id"))
    run_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    source: Mapped[str] = mapped_column(String(16), default="solver")  # solver | manual
    locked: Mapped[bool] = mapped_column(Boolean, default=False)


class Break(TenantOwned, Base):
    __tablename__ = "breaks"
    assignment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assignments.id", ondelete="CASCADE"))
    minutes: Mapped[int] = mapped_column(Integer)
    paid: Mapped[bool] = mapped_column(Boolean, default=False)


class BrandAllocation(TenantOwned, Base):
    """Imputation des heures effectives d'une affectation à un budget/marque (sans doubler les heures)."""
    __tablename__ = "brand_allocations"
    assignment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assignments.id", ondelete="CASCADE"))
    brand_code: Mapped[str] = mapped_column(String(64))
    minutes: Mapped[int] = mapped_column(Integer)


class ConstraintDefinition(TenantOwned, Base):
    """Règles versionnées : legal | exception | internal | unavailability | preference."""
    __tablename__ = "constraint_definitions"
    kind: Mapped[str] = mapped_column(String(16))
    code: Mapped[str] = mapped_column(String(64))
    scope: Mapped[str] = mapped_column(String(16), default="tenant")  # tenant | employee
    employee_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"))
    params: Mapped[Any] = mapped_column(JSONB, default=dict)
    jurisdiction: Mapped[Optional[str]] = mapped_column(String(64))  # pays/canton/secteur/convention
    valid_from: Mapped[Optional[date]] = mapped_column(Date)
    valid_to: Mapped[Optional[date]] = mapped_column(Date)
    version: Mapped[int] = mapped_column(Integer, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    enabled_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    exception_reason: Mapped[Optional[str]] = mapped_column(Text)
    legal_review_status: Mapped[str] = mapped_column(String(24), default="a_valider")


class EmployeePreference(TenantOwned, Base):
    __tablename__ = "employee_preferences"
    employee_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(32))  # latest_start|preferred_times|preferred_tags|weekly_rest_days
    params: Mapped[Any] = mapped_column(JSONB, default=dict)
    strength: Mapped[int] = mapped_column(Integer, default=1)
    is_hard: Mapped[bool] = mapped_column(Boolean, default=False)


class RelationshipPreference(TenantOwned, Base):
    __tablename__ = "relationship_preferences"
    employee_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"))
    other_employee_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(32), default="opposite_shifts")
    note: Mapped[Optional[str]] = mapped_column(String(200))


class OptimizationRun(TenantOwned, Base):
    __tablename__ = "optimization_runs"
    period_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("planning_periods.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(24), default="en_attente")  # en_attente|en_cours|termine|annule|erreur
    kind: Mapped[str] = mapped_column(String(16), default="full")  # full | partial
    config: Mapped[Any] = mapped_column(JSONB, default=dict)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(100))
    requested_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (UniqueConstraint("tenant_id", "idempotency_key"),)


class OptimizationResult(TenantOwned, Base):
    __tablename__ = "optimization_results"
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("optimization_runs.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(32))
    mode: Mapped[str] = mapped_column(String(32))
    duration_s: Mapped[float] = mapped_column(Float)
    report: Mapped[Any] = mapped_column(JSONB)  # budgets, objectifs, poids, préférences, diagnostics, données manquantes


class Conflict(TenantOwned, Base):
    __tablename__ = "conflicts"
    run_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("optimization_runs.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String(48))
    severity: Mapped[str] = mapped_column(String(16))
    message: Mapped[str] = mapped_column(Text)
    slots: Mapped[Any] = mapped_column(JSONB, default=list)


class ScheduleVersion(TenantOwned, Base):
    __tablename__ = "schedule_versions"
    period_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("planning_periods.id", ondelete="CASCADE"))
    number: Mapped[int] = mapped_column(Integer)
    label: Mapped[Optional[str]] = mapped_column(String(100))
    snapshot: Mapped[Any] = mapped_column(JSONB)  # [{slot_key, employee_code, locked, ...}]
    exploratory: Mapped[bool] = mapped_column(Boolean, default=True)
    published: Mapped[bool] = mapped_column(Boolean, default=False)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))


class LockedAssignment(TenantOwned, Base):
    __tablename__ = "locked_assignments"
    assignment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assignments.id", ondelete="CASCADE"))
    locked_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    reason: Mapped[Optional[str]] = mapped_column(String(200))


class AuditLog(TenantOwned, Base):
    __tablename__ = "audit_logs"
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    action: Mapped[str] = mapped_column(String(64))
    entity: Mapped[Optional[str]] = mapped_column(String(64))
    entity_id: Mapped[Optional[str]] = mapped_column(String(64))
    detail: Mapped[Any] = mapped_column(JSONB, default=dict)  # jamais de secrets/mots de passe


class ExportJob(TenantOwned, Base):
    __tablename__ = "export_jobs"
    kind: Mapped[str] = mapped_column(String(16))  # pdf|xlsx|csv|ics
    filters: Mapped[Any] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="termine")
    requested_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))


TENANT_TABLES = [t.name for t in Base.metadata.sorted_tables if "tenant_id" in t.c and t.name != "sessions"]
