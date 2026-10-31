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
    # --- paramètres de la fiche collaborateur ---
    max_days_count: Optional[int] = None  # nombre max de jours travaillés (contrainte dure)
    max_days_period: Optional[str] = None  # "week" | "month" ; None = pas de préférence
    time_pref: Optional[str] = None  # "matin" | "middle" | "soir" ; None = pas de préférence
    time_pref_strict: bool = False  # True : obligatoire (dur) ; False : souple
    sunday_quota: Optional[int] = None  # nombre de dimanches sur la période ; None = pas de préférence
    sunday_mode: str = "max"  # "max" : plafond dur ; "exact" : objectif (plafond dur + manque pénalisé)

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
    strict: bool = True  # strict : plafond dur ; sinon dépassement autorisé mais pénalisé


@dataclass(frozen=True)
class OutsideShift:
    """Shift réalisé hors de la période planifiée (période voisine) : sert aux semaines à cheval sur deux mois,
    aux jours consécutifs et au repos à la frontière. Jamais deviné : fourni par les plannings existants."""
    employee_id: str
    day: date
    start: time
    end: time


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
    "time_pref": 8,  # par shift hors préférence horaire souple (x force)
    "sunday_quota": 500,  # par dimanche manquant d'un objectif exact
    "budget_over": 800,  # par heure au-delà d'un budget non strict
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
    outside_shifts: List[OutsideShift] = field(default_factory=list)
    history_provided: bool = False  # des plannings voisins ont été fournis pour les semaines à cheval
    site_starts: Dict[str, List[time]] = field(default_factory=dict)  # horaires autorisés par boutique (début)
    allowed_times: Dict[str, List[Tuple[time, time]]] = field(default_factory=dict)  # scope (site|marque) -> horaires


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
    sunday: Dict[str, object] = field(default_factory=dict)  # compteur et quotas des dimanches

    def to_dict(self) -> dict:
        return asdict(self)


# ---- préférence horaire : catégories selon l'heure de début ----
CATEGORIES = ("matin", "middle", "soir")
CATEGORY_LABEL = {"matin": "Matin", "middle": "Middle shift", "soir": "Soir"}


def time_category(start: time) -> str:
    """Matin : début avant 9 h (6 h, 7 h, 8 h) ; middle : 9 h à 11 h 59 (10 h, 11 h) ; soir : à partir de 12 h."""
    h = start.hour + start.minute / 60
    return "matin" if h < 9 else ("middle" if h < 12 else "soir")


def site_start_times(inp: "SolverInput") -> Dict[str, List[time]]:
    """Horaires réellement disponibles par boutique : paramètres si fournis, sinon début des shifts générés."""
    out: Dict[str, set] = {}
    for site, starts in inp.site_starts.items():
        out.setdefault(site, set()).update(starts)
    for sl in inp.slots:
        if sl.site not in inp.site_starts:
            out.setdefault(sl.site, set()).add(sl.start)
    return {k: sorted(v) for k, v in out.items()}


def slot_category(slot: "Slot", starts_by_site: Dict[str, List[time]]) -> Optional[str]:
    """Catégorie du shift, ou None (neutre) si la boutique n'a qu'un seul horaire : aucune préférence n'a de sens."""
    if len(starts_by_site.get(slot.site, [slot.start])) < 2:
        return None
    return time_category(slot.start)
