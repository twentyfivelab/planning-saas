"""Modèle normalisé. Toutes les tables métier portent tenant_id (+ RLS, voir migration)."""
import uuid
from datetime import date, datetime, time
from typing import Any, Optional

from sqlalchemy import (Boolean, CheckConstraint, Date, DateTime, Float, ForeignKey, Integer, String, Text, Time, UniqueConstraint,
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
    # conservation des versions AUTOMATIQUES d'un planning (jamais les versions manuelles, validées ou publiées) ; NULL = sans limite
    version_keep_per_month: Mapped[Optional[int]] = mapped_column(Integer, default=20, server_default="20")
    version_max_age_days: Mapped[Optional[int]] = mapped_column(Integer)
    # règle interne de l'entreprise (pas une valeur légale) : travail effectif maximal par collaborateur et par mois, tous sites et
    # toutes marques cumulés ; NULL = aucun plafond
    monthly_hours_cap_minutes: Mapped[Optional[int]] = mapped_column(Integer, default=10560, server_default="10560")
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
    scope: Mapped[Any] = mapped_column(JSONB, default=dict, server_default="{}")  # périmètre d'un responsable de marque : {"brands": [...]}


class Client(TenantOwned, Base):
    """Entreprise cliente de la société de placement : ses marques, missions, contrats commerciaux et responsables."""
    __tablename__ = "clients"
    code: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(200))
    legal_name: Mapped[Optional[str]] = mapped_column(String(200))
    contacts: Mapped[Any] = mapped_column(JSONB, default=list, server_default="[]")  # responsables : [{name, role, email, phone}]
    billing_rate_cents: Mapped[Optional[int]] = mapped_column(Integer)  # tarif horaire de facturation saisi ; NULL = non renseigné (jamais supposé)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint("tenant_id", "code"),)


class ClientContract(TenantOwned, Base):
    """Contrat commercial avec un client : période, heures commandées, tarif."""
    __tablename__ = "client_contracts"
    client_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"))
    reference: Mapped[str] = mapped_column(String(100))
    start_date: Mapped[Optional[date]] = mapped_column(Date)
    end_date: Mapped[Optional[date]] = mapped_column(Date)
    ordered_minutes: Mapped[Optional[int]] = mapped_column(Integer)
    billing_rate_cents: Mapped[Optional[int]] = mapped_column(Integer)
    notes: Mapped[Optional[str]] = mapped_column(Text)


class Site(TenantOwned, Base):
    __tablename__ = "sites"
    code: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(200))
    open_weekdays: Mapped[Any] = mapped_column(JSONB, default=list)
    # le code est l'identifiant STABLE (référencé par les shifts et les besoins) ; seul le nom est modifiable.
    archived_from: Mapped[Optional[date]] = mapped_column(Date)  # 1er mois sans ce site ; les mois antérieurs restent intacts
    __table_args__ = (UniqueConstraint("tenant_id", "code"),)


class Brand(TenantOwned, Base):
    __tablename__ = "brands"
    code: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(200))
    active_weekdays: Mapped[Any] = mapped_column(JSONB, default=list)  # jours de fonctionnement
    group_code: Mapped[Optional[str]] = mapped_column(String(64))  # ex. COSMETIQUE
    archived_from: Mapped[Optional[date]] = mapped_column(Date)  # code stable ; archivage à partir d'un mois, historique conservé
    client_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("clients.id", ondelete="SET NULL"))
    billing_rate_cents: Mapped[Optional[int]] = mapped_column(Integer)  # tarif horaire propre à la marque (prime sur celui du client)
    __table_args__ = (UniqueConstraint("tenant_id", "code"),)


class Skill(TenantOwned, Base):
    __tablename__ = "skills"
    code: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(16), default="competence", server_default="competence")  # competence | formation | langue | certification | qualification
    __table_args__ = (UniqueConstraint("tenant_id", "code"),)


class Employee(TenantOwned, Base):
    __tablename__ = "employees"
    code: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(200))
    brands: Mapped[Any] = mapped_column(JSONB, default=dict)  # {brand_code: priority|reinforce}
    allocation_weight: Mapped[float] = mapped_column(Float, default=1.0)  # préférence souple
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # --- fiche collaborateur : limites et préférences transmises au moteur ---
    max_days_count: Mapped[Optional[int]] = mapped_column(Integer)  # NULL = pas de préférence
    max_days_period: Mapped[Optional[str]] = mapped_column(String(8))  # week | month
    time_pref: Mapped[Optional[str]] = mapped_column(String(8))  # matin | middle | soir
    time_pref_strict: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    sunday_quota: Mapped[Optional[int]] = mapped_column(Integer)  # NULL = pas de préférence
    sunday_mode: Mapped[str] = mapped_column(String(8), default="max", server_default="max")  # max | exact
    # quota historique (valeur unique d'avant les paramètres mensuels) : conservé tel quel ; une fois reporté sur les mois, il ne sert plus de défaut
    sunday_quota_migrated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    # identité (fiche d'ajout) : NULL = non renseigné, jamais deviné ; `name` reste le nom affiché (« Prénom Nom »)
    first_name: Mapped[Optional[str]] = mapped_column(String(100))
    last_name: Mapped[Optional[str]] = mapped_column(String(100))
    birth_date: Mapped[Optional[date]] = mapped_column(Date)
    address_street: Mapped[Optional[str]] = mapped_column(String(200))
    address_postal_code: Mapped[Optional[str]] = mapped_column(String(16))
    address_city: Mapped[Optional[str]] = mapped_column(String(100))
    address_country: Mapped[Optional[str]] = mapped_column(String(100))
    phone: Mapped[Optional[str]] = mapped_column(String(32))
    email: Mapped[Optional[str]] = mapped_column(String(200))
    # jours travaillés par mois civil : NULL = pas de préférence (le plafond mensuel d'heures reste appliqué)
    min_days_month: Mapped[Optional[int]] = mapped_column(Integer)
    max_days_month: Mapped[Optional[int]] = mapped_column(Integer)
    # suppression : retiré des prochaines planifications, affectations et historique conservés
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    removed_on: Mapped[Optional[date]] = mapped_column(Date)  # plus aucun shift à partir de cette date
    deleted_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    __table_args__ = (UniqueConstraint("tenant_id", "code"),
                      CheckConstraint("min_days_month IS NULL OR (min_days_month BETWEEN 1 AND 31)", name="ck_emp_min_days_month"),
                      CheckConstraint("max_days_month IS NULL OR (max_days_month BETWEEN 1 AND 31)", name="ck_emp_max_days_month"),
                      CheckConstraint("min_days_month IS NULL OR max_days_month IS NULL OR min_days_month <= max_days_month", name="ck_emp_days_order"))


class EmployeeSkill(TenantOwned, Base):
    __tablename__ = "employee_skills"
    employee_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"))
    skill_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("skills.id", ondelete="CASCADE"))
    valid_until: Mapped[Optional[date]] = mapped_column(Date)  # certification à échéance : plus prise en compte après cette date
    __table_args__ = (UniqueConstraint("employee_id", "skill_id"),)


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
    contract_type: Mapped[Optional[str]] = mapped_column(String(32))  # CDI, CDD, mission…
    hourly_cost_cents: Mapped[Optional[int]] = mapped_column(Integer)  # coût horaire employeur saisi ; NULL = non renseigné (jamais supposé)
    legal_regime: Mapped[Optional[str]] = mapped_column(String(64))  # régime applicable (référentiel juridique) ; NULL = règles générales du tenant


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
    # portée des horaires autorisés : site (code de boutique), marque, ou groupe de marques (ex. ALCOOL)
    scope_type: Mapped[Optional[str]] = mapped_column(String(8))
    scope_code: Mapped[Optional[str]] = mapped_column(String(64))
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
    headcount: Mapped[int] = mapped_column(Integer, default=1, server_default="1")  # personnes nécessaires sur ce shift
    # validité : une modification depuis un mois crée une nouvelle version ; les mois précédents gardent l'ancienne
    valid_from: Mapped[Optional[date]] = mapped_column(Date)
    valid_to: Mapped[Optional[date]] = mapped_column(Date)
    mission_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("missions.id", ondelete="CASCADE"))  # besoin créé par une mission client
    priority: Mapped[int] = mapped_column(Integer, default=3, server_default="3")  # 1 (basse) … 5 (critique)


class Mission(TenantOwned, Base):
    """Demande d'un client (événement, renfort, animation ponctuelle) : une fois confirmée, elle crée des besoins que le moteur
    intègre à la planification, à côté des animations permanentes. Annulée ou en brouillon : aucun besoin n'est planifié."""
    __tablename__ = "missions"
    code: Mapped[str] = mapped_column(String(48))
    client_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clients.id"))
    brand_code: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(200))
    site_codes: Mapped[Any] = mapped_column(JSONB, default=list)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    weekdays: Mapped[Any] = mapped_column(JSONB, default=list)
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)
    break_minutes: Mapped[int] = mapped_column(Integer, default=60)
    headcount: Mapped[int] = mapped_column(Integer, default=1)
    required_skills: Mapped[Any] = mapped_column(JSONB, default=list)
    budget_minutes: Mapped[Optional[int]] = mapped_column(Integer)  # heures commandées pour la mission
    billing_rate_cents: Mapped[Optional[int]] = mapped_column(Integer)  # tarif propre à la mission (prime sur marque et client)
    priority: Mapped[int] = mapped_column(Integer, default=3)
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft | confirmed | cancelled | completed
    notes: Mapped[Optional[str]] = mapped_column(Text)
    cancelled_reason: Mapped[Optional[str]] = mapped_column(String(300))
    renewed_from: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    __table_args__ = (UniqueConstraint("tenant_id", "code"),
                      CheckConstraint("priority BETWEEN 1 AND 5", name="ck_mission_priority"),
                      CheckConstraint("headcount BETWEEN 1 AND 200", name="ck_mission_headcount"),
                      CheckConstraint("end_date >= start_date", name="ck_mission_dates"),
                      CheckConstraint("status IN ('draft','confirmed','cancelled','completed')", name="ck_mission_status"))


class MonthlyBudget(TenantOwned, Base):
    __tablename__ = "monthly_budgets"
    brand_code: Mapped[str] = mapped_column(String(64))
    month: Mapped[date] = mapped_column(Date)  # 1er du mois
    target_minutes: Mapped[int] = mapped_column(Integer)  # travail effectif
    requirements_defined: Mapped[bool] = mapped_column(Boolean, default=True)
    strict: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")  # strict = plafond jamais dépassé
    __table_args__ = (UniqueConstraint("tenant_id", "brand_code", "month"),)


class PlanningPeriod(TenantOwned, Base):
    __tablename__ = "planning_periods"
    name: Mapped[str] = mapped_column(String(100))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))  # archivé = consultable, non modifiable
    wizard_step: Mapped[Optional[int]] = mapped_column(Integer)  # étape de l'assistant à reprendre (brouillon)
    # paramètres conservés par CE planning (fiches, disponibilités récurrentes, règles) : un changement fait pour un autre mois ne le
    # modifie pas ; ils ne sont remplacés que par une action explicite (« Appliquer les paramètres actuels » ou génération choisie ainsi)
    frozen_params: Mapped[Any] = mapped_column(JSONB, nullable=True)
    frozen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    frozen_source: Mapped[Optional[str]] = mapped_column(String(16))  # generation | manual | apply | mise_en_place


class PeriodEmployee(TenantOwned, Base):
    """Effectif du mois : un collaborateur décoché est exclu de CE mois uniquement (fiche, historique et autres mois intacts)."""
    __tablename__ = "period_employees"
    period_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("planning_periods.id", ondelete="CASCADE"))
    employee_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"))
    included: Mapped[bool] = mapped_column(Boolean, default=True)
    reason: Mapped[Optional[str]] = mapped_column(String(200))
    __table_args__ = (UniqueConstraint("period_id", "employee_id"),)


class PeriodBrand(TenantOwned, Base):
    """Marque active ou inactive pour un mois (par défaut : active)."""
    __tablename__ = "period_brands"
    period_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("planning_periods.id", ondelete="CASCADE"))
    brand_code: Mapped[str] = mapped_column(String(64))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (UniqueConstraint("period_id", "brand_code"),)


class PeriodSite(TenantOwned, Base):
    """Site actif ou inactif pour un mois (par défaut : actif)."""
    __tablename__ = "period_sites"
    period_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("planning_periods.id", ondelete="CASCADE"))
    site_code: Mapped[str] = mapped_column(String(64))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (UniqueConstraint("period_id", "site_code"),)


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
    __table_args__ = (UniqueConstraint("shift_id", name="uq_assignment_shift"),)  # un shift n'a jamais deux titulaires


class EmployeeMonthParams(TenantOwned, Base):
    """Paramètres propres à un mois (indépendants d'un mois à l'autre) : quota de dimanches du collaborateur."""
    __tablename__ = "employee_month_params"
    employee_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"))
    month: Mapped[date] = mapped_column(Date)  # 1er du mois
    sunday_quota: Mapped[Optional[int]] = mapped_column(Integer)  # NULL = pas de quota ce mois-là
    sunday_mode: Mapped[str] = mapped_column(String(8), default="exact", server_default="exact")  # max | exact
    # exception du mois sur le nombre maximum de jours (sinon : valeur habituelle de la fiche)
    max_days_set: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    max_days_count: Mapped[Optional[int]] = mapped_column(Integer)
    max_days_period: Mapped[Optional[str]] = mapped_column(String(8))
    # exception du mois sur les jours minimum / maximum par mois (sinon : valeurs habituelles de la fiche) ; NULL = pas de préférence
    days_set: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    min_days: Mapped[Optional[int]] = mapped_column(Integer)
    max_days: Mapped[Optional[int]] = mapped_column(Integer)
    __table_args__ = (UniqueConstraint("tenant_id", "employee_id", "month"),
                      CheckConstraint("sunday_quota IS NULL OR (sunday_quota >= 0 AND sunday_quota <= 5)", name="ck_month_sunday_quota"),
                      CheckConstraint("sunday_mode IN ('max','exact')", name="ck_month_sunday_mode"))


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
    source_url: Mapped[Optional[str]] = mapped_column(String(300))  # texte de référence (ex. SECO)
    reviewed_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


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
    kind: Mapped[str] = mapped_column(String(32), default="opposite_shifts")  # opposite_shifts | avoid_together | work_together | mentor
    note: Mapped[Optional[str]] = mapped_column(String(200))
    strict: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")  # contrainte dure (avoid_together, mentor) ; sinon préférence


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
    simulation: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")  # n'écrit JAMAIS dans le planning tant qu'elle n'est pas appliquée
    applied_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    progress: Mapped[Any] = mapped_column(JSONB, nullable=True)  # état du calcul en cours : étape, niveau, solutions trouvées, temps écoulé
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
    state: Mapped[str] = mapped_column(String(16), default="snapshot", server_default="snapshot")  # snapshot | in_review | validated | published | superseded
    kind: Mapped[str] = mapped_column(String(16), default="manual", server_default="manual")  # manual | generated | safety (copie automatique avant une opération)
    run_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    validated_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    validated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    published_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    note: Mapped[Optional[str]] = mapped_column(String(300))


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


class TimeEntry(TenantOwned, Base):
    """Heures réellement effectuées d'un shift : le prévu est recopié à la saisie et le planning n'est JAMAIS modifié."""
    __tablename__ = "time_entries"
    shift_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("shifts.id", ondelete="SET NULL"))
    period_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("planning_periods.id", ondelete="CASCADE"))
    employee_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("employees.id"))
    day: Mapped[date] = mapped_column(Date)
    site_code: Mapped[str] = mapped_column(String(64))
    allocations: Mapped[Any] = mapped_column(JSONB, default=dict)  # imputations prévues (marque -> minutes), figées à la saisie
    planned_start: Mapped[time] = mapped_column(Time)
    planned_end: Mapped[time] = mapped_column(Time)
    planned_break_minutes: Mapped[int] = mapped_column(Integer)
    planned_minutes: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="worked")  # worked | absent
    actual_start: Mapped[Optional[time]] = mapped_column(Time)
    actual_end: Mapped[Optional[time]] = mapped_column(Time)
    actual_break_minutes: Mapped[Optional[int]] = mapped_column(Integer)
    worked_minutes: Mapped[int] = mapped_column(Integer, default=0)
    late_minutes: Mapped[int] = mapped_column(Integer, default=0)
    overtime_minutes: Mapped[int] = mapped_column(Integer, default=0)
    absence_reason: Mapped[Optional[str]] = mapped_column(String(200))
    note: Mapped[Optional[str]] = mapped_column(String(300))
    entered_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    validated_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    validated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    __table_args__ = (UniqueConstraint("tenant_id", "shift_id", "employee_id", name="uq_time_entry_shift_employee"),
                      CheckConstraint("status IN ('worked','absent')", name="ck_time_status"),
                      CheckConstraint("worked_minutes >= 0", name="ck_time_worked"))


class Notification(TenantOwned, Base):
    """Notification interne : regroupée par publication (une seule par collaborateur, jamais une par modification)."""
    __tablename__ = "notifications"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(32))  # planning_published | planning_changed | replacement | ...
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[Optional[str]] = mapped_column(Text)
    payload: Mapped[Any] = mapped_column(JSONB, default=dict)
    read_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class ExportJob(TenantOwned, Base):
    __tablename__ = "export_jobs"
    kind: Mapped[str] = mapped_column(String(16))  # pdf|xlsx|csv|ics
    filters: Mapped[Any] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="termine")
    requested_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))


TENANT_TABLES = [t.name for t in Base.metadata.sorted_tables if "tenant_id" in t.c and t.name != "sessions"]
