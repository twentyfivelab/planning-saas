"""Interface d'entrée/sortie du moteur. Aucune dépendance à la base de données."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date, datetime, time
from typing import Dict, List, Optional, Set, Tuple

from .timecalc import shift_bounds, shift_hours

# Niveaux d'éligibilité marque -> coût de "renfort" appliqué par le solveur.
PRIORITY = "priority"
REINFORCE = "reinforce"


@dataclass(frozen=True)
class Slot:
    """Un shift à pourvoir (présence). Les allocations imputent le travail effectif aux budgets."""
    id: str
    day: date
    site: str
    start: time
    end: time
    break_minutes: int
    allocations: Dict[str, int]  # marque -> minutes effectives imputées (somme == effectif)
    tag: str = "day"  # open | day | mid | close
    template_id: str = ""
    required_skills: Tuple[str, ...] = ()
    mandatory: bool = True  # False: shift optionnel piloté par un budget (le solveur choisit les jours)
    day_group: Optional[str] = None  # au plus un slot rempli par groupe
    stagger_group: Optional[str] = None

    @property
    def hours(self):
        return shift_hours(self.day, self.start, self.end, self.break_minutes)

    @property
    def effective_minutes(self) -> int:
        return self.hours.effective_minutes

    @property
    def bounds(self) -> Tuple[datetime, datetime]:
        return shift_bounds(self.day, self.start, self.end)

    @property
    def brands(self) -> Tuple[str, ...]:
        return tuple(self.allocations)


@dataclass(frozen=True)
class Contract:
    """Uniquement des valeurs réellement saisies ; None = non renseigné (jamais deviné)."""
    activity_rate: Optional[float] = None
    monthly_min_minutes: Optional[int] = None
    monthly_target_minutes: Optional[int] = None
    monthly_max_minutes: Optional[int] = None
    weekly_max_minutes: Optional[int] = None
    overtime_allowed: bool = False


@dataclass
class Employee:
    id: str
    name: str
    brands: Dict[str, str]  # marque -> PRIORITY | REINFORCE
    skills: Set[str] = field(default_factory=set)
    contract: Optional[Contract] = None
    available_weekdays: Optional[Set[int]] = None  # None = non déclaré
    unavailable_weekdays: Set[int] = field(default_factory=set)
    unavailable_dates: Set[date] = field(default_factory=set)  # congés / absences
    forbidden_tags: Set[str] = field(default_factory=set)  # contrainte dure
    max_days_per_week: Optional[int] = None  # contrainte dure
    weekly_rest_days_pref: Optional[int] = None
    weekly_rest_days_hard: bool = False
    weight: float = 1.0  # poids d'attribution (préférence souple)
    latest_start: Optional[time] = None
    preferred_times: Set[Tuple[time, time]] = field(default_factory=set)
    preferred_tags: Set[str] = field(default_factory=set)
    preference_strength: int = 1
    opposite_of: Optional[str] = None  # préférence familiale
    prior_consecutive_days: int = 0

    def blocked(self, d: date) -> bool:
        wd = d.weekday()
        if wd in self.unavailable_weekdays or d in self.unavailable_dates:
            return True
        return self.available_weekdays is not None and wd not in self.available_weekdays


@dataclass
class BrandBudget:
    brand: str
    target_minutes: int
    requirements_defined: bool = True


DEFAULT_WEIGHTS: Dict[str, int] = {
    "coverage": 1000,  # par heure effective non couverte
    "budget": 800,  # par heure de budget non planifiée (shifts optionnels)
    "reinforce": 12,  # par heure en renfort
    "preference": 10,  # par préférence horaire/tag non respectée (x force)
    "fairness": 3,  # par demi-heure d'écart à la cible relative
    "overtime": 20,
    "site_change": 6,
    "balance": 4,
    "fatigue": 6,
    "family": 15,
    "stagger": 10,
    "rest_days": 40,
    "stability": 25,
}


@dataclass
class SolverConfig:
    rest_hours: int = 11  # référence initiale, à valider juridiquement
    max_consecutive_days: int = 6  # plafond interne initial
    stagger_minutes: int = 60
    weights: Dict[str, int] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    time_limit_s: float = 30.0
    workers: int = 8
    strict_coverage: bool = False  # True: toute couverture obligatoire devient dure (diagnostic de noyau)
    seed: int = 1


@dataclass
class SolverInput:
    period_start: date
    period_end: date
    slots: List[Slot]
    employees: List[Employee]
    budgets: List[BrandBudget]
    config: SolverConfig = field(default_factory=SolverConfig)
    locked: Dict[str, str] = field(default_factory=dict)  # slot_id -> employee_id
    previous: Dict[str, str] = field(default_factory=dict)  # affectations existantes (stabilité)
    leaves_provided: bool = False
    hypotheses: List[str] = field(default_factory=list)


@dataclass
class Assignment:
    slot_id: str
    employee_id: str
    day: date
    start: time
    end: time
    presence_minutes: int
    break_minutes: int
    effective_minutes: int
    allocations: Dict[str, int]
    locked: bool = False


@dataclass
class Issue:
    code: str
    severity: str  # info | warning | blocking
    message: str
    slots: List[str] = field(default_factory=list)
    constraints: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)


@dataclass
class SolverResult:
    status: str  # optimal | faisable | partiellement_couvert | infaisable | interrompu
    mode: str  # simulation_exploratoire | validable
    validable: bool
    duration_s: float
    assignments: List[Assignment]
    uncovered_slots: List[str]
    budgets: List[dict]
    objective: Dict[str, int]
    weights: Dict[str, int]
    preferences: Dict[str, dict]
    avoided_violations: Dict[str, int]
    missing_data: List[Issue]
    diagnostics: List[Issue]
    hard_violations: List[str]
    employee_hours: Dict[str, int]

    def to_dict(self) -> dict:
        return asdict(self)
