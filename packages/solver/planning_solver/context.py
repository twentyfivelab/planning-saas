"""Préparation commune au moteur CP-SAT, à l'évaluateur de la fonction objectif, au classement des remplaçants et aux
explications : éligibilité (préfiltrage des affectations impossibles), cibles d'équité, catégories horaires… Un seul calcul,
partagé, pour que le moteur et les outils d'analyse appliquent exactement les mêmes règles."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Dict, List, Optional, Set, Tuple

from .model import Employee, Slot, SolverInput, site_start_times, slot_category
from .sundays import sundays_in
from .timecalc import shift_bounds

# priorité d'un besoin (1 = basse … 5 = critique) -> multiplicateur de la pénalité de non-couverture, en quarts
PRIORITY_QUARTERS = {1: 2, 2: 3, 3: 4, 4: 6, 5: 8}


def coverage_cost(weight: int, s: Slot) -> int:
    """Coût de non-couverture d'un shift obligatoire : poids × heures × facteur de priorité (entier)."""
    hrs = max(1, round(s.effective_minutes / 60))
    return (weight * hrs * PRIORITY_QUARTERS.get(s.priority, 4) + 2) // 4


def required_break(rules: List[Tuple[int, int]], s: Slot) -> int:
    """Pause minimale exigée par le référentiel juridique activé pour ce shift (0 si aucune règle)."""
    return max((brk for over, brk in rules if s.effective_minutes > over), default=0)


def hours_units(s: Slot) -> int:
    return max(1, round(s.effective_minutes / 60))


def window_overlap(s: Slot, d: date, a: time, b: time) -> bool:
    """Le shift chevauche le créneau [a, b[ du jour d (passage de minuit et changement d'heure compris)."""
    w0, w1 = shift_bounds(d, a, b)
    s0, s1 = s.bounds
    return s0 < w1 and w0 < s1


def within_window(s: Slot, w: Tuple[time, time]) -> bool:
    """Le shift tient dans les horaires obligatoires : début >= w[0], fin <= w[1], sans passer minuit."""
    return s.end > s.start and s.start >= w[0] and s.end <= w[1]


def ineligibility(e: Employee, s: Slot, starts_by_site: Dict[str, list]) -> Optional[Tuple[str, str]]:
    """Première règle stricte qui empêche `e` de prendre `s` ((code, explication)), ou None si l'affectation est admissible.
    C'est le préfiltrage du moteur : aucune variable de décision n'est créée pour une affectation impossible."""
    if e.excluded:
        return "EXCLUDED_FROM_PERIOD", "hors de l'effectif du mois"
    if e.left_on is not None and s.day >= e.left_on:
        return "EMPLOYEE_REMOVED", f"retiré·e de l'équipe le {e.left_on:%d/%m/%Y}"
    wd = s.day.weekday()
    if wd in e.unavailable_weekdays or s.day in e.unavailable_dates:
        return "UNAVAILABLE", "indisponible ce jour-là"
    if e.available_weekdays is not None and wd not in e.available_weekdays:
        return "UNAVAILABLE", "jour hors de ses disponibilités déclarées"
    for d, a, b in sorted(e.unavailable_windows):
        if d == s.day and window_overlap(s, d, a, b):
            return "UNAVAILABLE_PARTIAL", f"absent·e de {a:%H:%M} à {b:%H:%M} ce jour-là"
    if e.work_window is not None and not within_window(s, e.work_window):
        return "WORK_WINDOW", f"hors de ses horaires obligatoires ({e.work_window[0]:%H:%M}–{e.work_window[1]:%H:%M})"
    if wd in e.rest_weekdays_hard:
        return "REST_WEEKDAY", "jour de repos obligatoire (fiche)"
    if s.tag in e.forbidden_tags:
        return "FORBIDDEN_TAG", f"shift de type « {s.tag} » interdit (règle individuelle)"
    if e.time_pref and e.time_pref_strict:  # préférence horaire stricte = contrainte dure
        cat = slot_category(s, starts_by_site)
        if cat is not None and cat != e.time_pref:
            return "TIME_PREF_STRICT", f"shift « {cat} », préférence « {e.time_pref} » obligatoire"
    if e.sunday_quota == 0 and wd == 6:  # 0 dimanche : interdiction dure
        return "SUNDAY_QUOTA", "quota de 0 dimanche"
    missing = [b for b in s.brands if b not in e.brands]
    if missing:
        return "BRAND_NOT_ELIGIBLE", f"marque non autorisée ({', '.join(missing)})"
    if e.allowed_sites is not None and s.site not in e.allowed_sites:
        return "SITE_NOT_ALLOWED", f"site {s.site} non autorisé (fiche)"
    lacking = [k for k in s.required_skills if k not in e.skills]
    if lacking:
        return "SKILL_MISSING", f"qualification manquante ({', '.join(lacking)})"
    return None


@dataclass
class Prepared:
    inp: SolverInput
    slots: Dict[str, Slot]
    emps: Dict[str, Employee]
    days: List[date]
    starts_by_site: Dict[str, list]
    outside: Dict[str, List[Tuple[datetime, datetime]]]
    by_emp: Dict[str, List[Slot]]
    eligible: Set[Tuple[str, str]]
    suns: List[date]
    optional_brands: Set[str]
    fair_cap: Dict[str, int]  # capacité seul (minutes) : un shift par jour sur ses shifts autorisés (renfort compris), limites dures de la fiche
    fair_explicit: Dict[str, int]  # objectif contractuel explicite, plafonné par la capacité
    fair_contract: Dict[str, int]  # objectif contractuel tel que saisi
    budgeted_brands: Set[str]  # marques ayant un budget ce mois (leurs besoins optionnels comptent dans le volume visé)
    wmax: float
    category: Dict[str, Optional[str]] = field(default_factory=dict)  # slot -> matin | middle | soir | None
    # mois civils de la période -> jours ; jours et minutes déjà travaillés hors période dans ces mêmes mois (périodes voisines)
    months: Dict[Tuple[int, int], List[date]] = field(default_factory=dict)
    outside_month_days: Dict[Tuple[str, Tuple[int, int]], Set[date]] = field(default_factory=dict)
    outside_month_minutes: Dict[Tuple[str, Tuple[int, int]], int] = field(default_factory=dict)
    fair_days: Dict[str, Dict[date, int]] = field(default_factory=dict)  # par collaborateur : minutes maximales par jour (un shift)
    fair_weeks: Dict[str, Dict[tuple, int]] = field(default_factory=dict)  # par collaborateur : minutes maximales par semaine ISO
    fair_supply: int = 0  # volume estimé avant calcul : besoins obligatoires + budgets du mois
    _estimate: Optional[Tuple[Dict[str, int], Dict[str, int]]] = field(default=None, repr=False)

    @property
    def targets(self) -> Dict[str, int]:
        """Cible ESTIMÉE (avant calcul) : volume = obligatoires + budgets. Le moteur hiérarchisé la remplace par la cible calculée sur le
        volume réellement décidé (`realized_targets`) ; en mode à un seul niveau, c'est elle qui s'applique."""
        return self._estimated()[0]

    @property
    def fair_ref(self) -> Dict[str, int]:
        return self._estimated()[1]

    def _estimated(self):
        if self._estimate is None:
            self._estimate = flow_targets(self, list(self.slots), self.fair_supply)
        return self._estimate

    def has_sunday_option(self, eid: str) -> bool:
        return any(s.day.weekday() == 6 for s in self.by_emp.get(eid, ()))


def _days(inp: SolverInput) -> List[date]:
    d, out = inp.period_start, []
    while d <= inp.period_end:
        out.append(d)
        d += timedelta(days=1)
    return out


def prepare(inp: SolverInput) -> Prepared:
    starts_by_site = site_start_times(inp)
    rest_td = timedelta(hours=inp.config.rest_hours)
    outside: Dict[str, list] = defaultdict(list)
    for o in inp.outside_shifts:
        outside[o.employee_id].append(shift_bounds(o.day, o.start, o.end))

    def clashes_outside(e: Employee, s: Slot) -> bool:
        """Chevauchement ou repos insuffisant avec un shift d'une période voisine."""
        b0, b1 = s.bounds
        return any(o0 < b1 + rest_td and b0 < o1 + rest_td for o0, o1 in outside.get(e.id, ()))

    by_emp: Dict[str, List[Slot]] = defaultdict(list)
    eligible: Set[Tuple[str, str]] = set()
    rules = inp.config.break_rules
    for e in inp.employees:
        for s in inp.slots:
            if s.break_minutes < required_break(rules, s):  # pause insuffisante : shift signalé, jamais pourvu tant qu'il n'est pas corrigé
                continue
            if ineligibility(e, s, starts_by_site) is None and not clashes_outside(e, s):
                eligible.add((e.id, s.id))
                by_emp[e.id].append(s)
    days = _days(inp)
    months: Dict[Tuple[int, int], List[date]] = defaultdict(list)
    for d in days:
        months[d.year, d.month].append(d)
    o_days: Dict[tuple, set] = defaultdict(set)
    o_min: Dict[tuple, int] = defaultdict(int)
    for o in inp.outside_shifts:
        key = (o.day.year, o.day.month)
        if key in months and not (inp.period_start <= o.day <= inp.period_end):
            o_days[o.employee_id, key].add(o.day)
            o_min[o.employee_id, key] += o.minutes
    optional_brands = {b for s in inp.slots if not s.mandatory for b in s.brands}
    # Équité : CIBLE COMMUNE d'heures mensuelles pour tous les collaborateurs de l'effectif du mois (y compris ceux qui ne sont qu'en renfort :
    # ce niveau départage ensuite, il n'exclut personne), plafonnée par ce que chacun peut réellement atteindre (`load_limits`) et par ce
    # qui reste atteignable compte tenu des collègues (`flow_targets`) ; objectif contractuel explicite le cas échéant. Exclusions explicites
    # respectées : hors de l'effectif du mois, contrat terminé, retiré de l'équipe (aucun shift possible, donc aucune cible). Jamais le
    # poids d'allocation : ni ancienneté ni mérite ne créent de priorité automatique.
    supply = sum(s.effective_minutes for s in inp.slots if s.mandatory)
    supply += sum(b.target_minutes for b in inp.budgets if b.brand in optional_brands)
    caps: Dict[str, int] = {}
    explicit: Dict[str, int] = {}
    f_days: Dict[str, Dict[date, int]] = {}
    f_weeks: Dict[str, Dict[tuple, int]] = {}
    out_week_days: Dict[tuple, set] = defaultdict(set)
    out_week_min: Dict[tuple, int] = defaultdict(int)
    for o in inp.outside_shifts:
        if not (inp.period_start <= o.day <= inp.period_end):
            out_week_days[o.employee_id, o.day.isocalendar()[:2]].add(o.day)
            out_week_min[o.employee_id, o.day.isocalendar()[:2]] += o.minutes
    for e in inp.employees:
        c = e.contract
        month_room = None
        if inp.config.monthly_cap_minutes is not None:  # jamais au-delà du plafond mensuel de l'entreprise
            month_room = sum(max(0, inp.config.monthly_cap_minutes - o_min.get((e.id, k), 0)) for k in months)
        f_days[e.id], f_weeks[e.id], caps[e.id] = load_limits(by_emp[e.id], e, month_room, out_week_days, out_week_min)
        if c and c.monthly_target_minutes:
            explicit[e.id] = min(c.monthly_target_minutes, caps[e.id])
    contract = {e.id: e.contract.monthly_target_minutes for e in inp.employees if e.id in explicit}
    return Prepared(inp=inp, slots={s.id: s for s in inp.slots}, emps={e.id: e for e in inp.employees}, days=days,
                    starts_by_site=starts_by_site, outside=dict(outside), by_emp=by_emp, eligible=eligible, suns=sundays_in(inp),
                    optional_brands=optional_brands, fair_cap=caps, fair_explicit=explicit, fair_contract=contract,
                    budgeted_brands={b.brand for b in inp.budgets}, wmax=max((e.weight for e in inp.employees), default=0),
                    category={s.id: slot_category(s, starts_by_site) for s in inp.slots}, months=dict(months),
                    outside_month_days=dict(o_days), outside_month_minutes=dict(o_min), fair_days=f_days, fair_weeks=f_weeks, fair_supply=supply)


def min_days_need(prep: Prepared, e: Employee, key: Tuple[int, int]) -> int:
    """Jours encore à travailler dans la période pour atteindre le minimum du mois (jours déjà travaillés hors période déduits)."""
    if not e.min_days_month:
        return 0
    return max(0, e.min_days_month - len(prep.outside_month_days.get((e.id, key), ())))


def period_of(s: Slot) -> str:
    """Moment de la journée pour les relations entre collaborateurs (horaires opposés) : matin / milieu / après-midi."""
    h = s.start.hour + s.start.minute / 60
    return "matin" if h < 10 else ("apres_midi" if h >= 12 else "milieu")


def preference_checks(e: Employee, s: Slot) -> List[tuple]:
    """[(code, satisfait, force)] pour les préférences applicables à (employé, slot)."""
    out = []
    if e.latest_start is not None:
        out.append(("start<=%s" % e.latest_start.strftime("%H:%M"), s.start <= e.latest_start, 1))
    if e.preferred_times:
        out.append(("horaire_prefere", (s.start, s.end) in e.preferred_times, 1))
    if e.preferred_tags:
        out.append(("tag_prefere:" + "/".join(sorted(e.preferred_tags)), s.tag in e.preferred_tags,
                    e.preference_strength))
    if e.rest_weekdays_soft:
        out.append(("repos_souhaite", s.day.weekday() not in e.rest_weekdays_soft, 1))
    if e.preferred_sites:
        out.append(("site_prefere", s.site in e.preferred_sites, 1))
    return out


def relation_pairs(prep: Prepared) -> List[Tuple[str, Employee, List[str], bool, str]]:
    """Relations exploitables (les deux collaborateurs sont dans le problème) : (type, collaborateur, autres, stricte, portée).
    Les relations « mentor » d'un même collaborateur sont regroupées : au moins un des tuteurs doit être présent."""
    out = []
    for e in prep.inp.employees:
        mentors = [r for r in e.relations if r.kind == "mentor" and r.other in prep.emps and r.other != e.id]
        if mentors:  # plusieurs tuteurs : la portée la plus exigeante s'applique (couverture complète > chevauchement > même jour)
            scope = max((getattr(r, "scope", "site_day") for r in mentors), key=lambda x: PRESENCE_ORDER.get(x, 0))
            out.append(("mentor", e, sorted({r.other for r in mentors}), any(r.strict for r in mentors), scope))
        for r in e.relations:
            if r.kind in ("avoid_together", "work_together") and r.other in prep.emps and r.other != e.id:
                if e.id < r.other or not any(x.kind == r.kind and x.other == e.id for x in prep.emps[r.other].relations):
                    out.append((r.kind, e, [r.other], r.strict and r.kind == "avoid_together", getattr(r, "scope", "site_day")))
    return out


PRESENCE_ORDER = {"site_day": 0, "overlap": 1, "full": 2}


def presence_needs(prep: Prepared, eid: str, others: List[str], scope: str):
    """Tuteur ou binôme de portée « overlap » (chevauchement simple) ou « full » (couverture complète), même site. Pour chaque shift
    possible de `eid`, la liste des exigences : chacune est un ensemble de (autre collaborateur, shift) dont AU MOINS UN doit être tenu.
    - overlap : une exigence = tous les shifts des autres qui chevauchent le sien (au moins un moment en commun) ;
    - full : la plage du shift est découpée aux débuts et fins des shifts des autres ; chaque morceau doit être couvert par un shift
      qui le contient entièrement (plusieurs tuteurs peuvent se relayer). Un morceau que personne ne peut couvrir donne une exigence vide."""
    theirs = [(o, b) for o in others for b in prep.by_emp.get(o, ())]
    for a in prep.by_emp.get(eid, ()):
        a0, a1 = a.bounds
        near = [(o, b) for o, b in theirs if b.site == a.site and b.bounds[0] < a1 and a0 < b.bounds[1]]
        if scope == "overlap":
            yield a, [near]
            continue
        cuts = sorted({a0, a1, *(t for _o, b in near for t in b.bounds if a0 < t < a1)})
        yield a, [[(o, b) for o, b in near if b.bounds[0] <= i0 and b.bounds[1] >= i1] for i0, i1 in zip(cuts, cuts[1:])]


def presence_ok(slot: Slot, held: List[Slot], scope: str) -> bool:
    """Même règle sur un planning donné (vérificateur, évaluateur) : `held` = shifts tenus par le tuteur ou le binôme ce jour-là."""
    a0, a1 = slot.bounds
    near = [b for b in held if b.site == slot.site and b.bounds[0] < a1 and a0 < b.bounds[1]]
    if scope == "overlap":
        return bool(near)
    t = a0
    for b0, b1 in sorted(b.bounds for b in near):
        if b0 > t:
            return False
        t = max(t, b1)
        if t >= a1:
            return True
    return t >= a1


def history_excess(prep: Prepared) -> Dict[Tuple[str, str], int]:
    """Excédent de chaque collaborateur sur la moyenne de l'équipe (week-ends et dimanches des mois précédents), arrondi à l'entier inférieur.
    Seuls les collaborateurs de l'effectif du mois comptent dans la moyenne ; sans historique fourni, aucun excédent."""
    team = [e for e in prep.inp.employees if not e.excluded and e.left_on is None]
    out: Dict[Tuple[str, str], int] = {}
    if not team or not any(e.history for e in team):
        return out
    for key in ("weekends", "sundays"):
        mean = sum(e.history.get(key, 0) for e in team) / len(team)
        for e in team:
            ex = int(e.history.get(key, 0) - mean)
            if ex > 0:
                out[e.id, key] = ex
    return out


def overlaps(a: Slot, b: Slot) -> bool:
    """Horaires qui se chevauchent (passage de minuit et changement d'heure compris)."""
    (s1, e1), (s2, e2) = a.bounds, b.bounds
    return s1 < e2 and s2 < e1


def scoped_avoid_pairs(prep: Prepared, eid: str, others: List[str], scope: str):
    """Paires de shifts (jour, shift de eid, autre collaborateur, son shift) interdites ou pénalisées par une relation « à séparer » de portée
    « day » (même jour, tous sites) ou « overlap » (horaires qui se chevauchent, tous sites)."""
    for o in others:
        theirs: Dict = defaultdict(list)
        for s in prep.by_emp.get(o, ()):
            theirs[s.day].append(s)
        for a in prep.by_emp.get(eid, ()):
            if scope == "day":
                for b in theirs.get(a.day, ()):
                    yield a.day, a, o, b
            else:
                for dd in (a.day - timedelta(days=1), a.day, a.day + timedelta(days=1)):
                    for b in theirs.get(dd, ()):
                        if overlaps(a, b):
                            yield a.day, a, o, b


FAIR_TIERS = (32, 80)  # écart (demi-heures) au-delà duquel chaque demi-heure coûte une unité de plus : 16 h, puis 40 h


def fairness_units(dev_half_hours: int) -> int:
    """Coût d'un écart à la part équitable : progressif (au-delà de 16 h puis de 40 h), si bien qu'entre collaborateurs comparables
    un manque (ou un surplus) est réparti au lieu d'être concentré sur l'un d'eux."""
    return dev_half_hours + sum(max(0, dev_half_hours - t) for t in FAIR_TIERS)


def week_limits(e: Employee) -> Tuple[Optional[int], Optional[int]]:
    """Limites hebdomadaires dures de la fiche : (jours maximum, minutes maximum) ; None = aucune."""
    k = [v for v in (e.max_days_per_week, e.max_days_count if e.max_days_period == "week" else None,
                     7 - e.weekly_rest_days_pref if e.weekly_rest_days_hard and e.weekly_rest_days_pref is not None else None) if v is not None]
    mins = [v for v in (e.contract.weekly_max_minutes if e.contract else None, e.legal_weekly_max_minutes) if v is not None]
    return (min(k) if k else None), (min(mins) if mins else None)


def load_limits(slots, e: Employee, month_room: Optional[int] = None, out_week_days=None, out_week_min=None):
    """Ce qu'un collaborateur peut faire SEUL : un shift par jour (le plus long parmi ses shifts autorisés, renfort compris), limites dures
    de la fiche — jours et minutes par semaine (y compris ceux d'une période voisine dans la même semaine), jours par mois, plafond
    mensuel du contrat et de l'entreprise. Renvoie (minutes par jour, minutes par semaine, total)."""
    per_day: Dict[date, int] = {}
    for s in slots:
        per_day[s.day] = max(per_day.get(s.day, 0), s.effective_minutes)
    kd, km = week_limits(e)
    weeks: Dict[tuple, List[int]] = defaultdict(list)
    for d, mi in per_day.items():
        weeks[d.isocalendar()[:2]].append(mi)
    week_cap: Dict[tuple, int] = {}
    vals: List[int] = []
    for wkey, v in weeks.items():
        v = sorted(v, reverse=True)
        if kd is not None:
            v = v[: max(0, kd - len((out_week_days or {}).get((e.id, wkey), ())))]
        room = None if km is None else max(0, km - (out_week_min or {}).get((e.id, wkey), 0))
        chosen = []
        for x in v:  # jours retenus dans la semaine, tronqués au plafond d'heures hebdomadaire
            if room is not None:
                x = min(x, room - sum(chosen))
            if x <= 0:
                break
            chosen.append(x)
        week_cap[wkey] = sum(chosen)
        vals += chosen
    vals.sort(reverse=True)
    lims = [x for x in (e.max_days_month, e.max_days_count if e.max_days_period == "month" else None) if x]
    total = sum(vals[: min(lims)] if lims else vals)
    c = e.contract
    for cap in (month_room, c.monthly_max_minutes if c and not c.overtime_allowed else None):
        if cap is not None:
            total = min(total, cap)
    return per_day, week_cap, total


def max_load_minutes(slots, e) -> int:
    """Capacité seul (compatibilité) : voir `load_limits`."""
    return load_limits(slots, e)[2]


def common_targets(supply: int, caps: Dict[str, int], explicit: Dict[str, int], contract: Dict[str, int], ids) -> Tuple[Dict[str, int], Dict[str, int]]:
    """Cible commune : objectif explicite (plafonné) pour ceux qui en ont un ; le reste du volume réparti à heures égales entre les
    autres, chacun plafonné par sa capacité (l'excédent des collaborateurs limités revient aux autres). Renvoie (cibles, références)."""
    pool = {i: 1 for i in ids if i not in explicit and caps.get(i, 0) > 0}
    shared = water_fill(max(0, supply - sum(explicit.values())), pool, caps) if pool else {}
    common = max(shared.values(), default=0)
    targets = {i: explicit.get(i, shared.get(i, 0)) for i in ids}
    refs = {i: (contract[i] if i in explicit else (common if i in pool else 0)) for i in ids}
    return targets, refs


def counted_minutes(prep: "Prepared", slot_ids) -> int:
    """Volume qui fixe la cible commune : shifts obligatoires et besoins optionnels des marques ayant un budget (les besoins optionnels
    sans budget n'ont pas de volume visé : l'équité peut en retenir pour rapprocher chacun de la cible, ils sont alors signalés)."""
    total = 0
    for sid in slot_ids:
        s = prep.slots.get(sid)
        if s is not None and (s.mandatory or any(b in prep.budgeted_brands for b in s.brands)):
            total += s.effective_minutes
    return total


def realized_targets(prep: "Prepared", slot_ids) -> Tuple[Dict[str, int], Dict[str, int]]:
    """Cibles calculées sur le volume RÉELLEMENT DÉCIDÉ (shifts obligatoires et besoins optionnels des marques ayant un budget, parmi
    `slot_ids`) et non sur le volume promis par les budgets, parfois inatteignable."""
    counted = [sid for sid in slot_ids if (s := prep.slots.get(sid)) is not None and _counts(prep, s)]
    return flow_targets(prep, counted, sum(prep.slots[sid].effective_minutes for sid in counted))


def _counts(prep: "Prepared", s: Slot) -> bool:
    return s.mandatory or any(b in prep.budgeted_brands for b in s.brands)


def flow_targets(prep: "Prepared", decided, supply: int) -> Tuple[Dict[str, int], Dict[str, int]]:
    """Cible commune plafonnée par ce que chacun peut réellement atteindre compte tenu des autres (`shared_fill`). Shifts atteignables :
    ceux de `decided`, plus les besoins optionnels sans budget (le moteur peut en retenir pour rapprocher quelqu'un de la cible) ; le
    total des cibles reste borné par `supply`. Renvoie (cibles, références : objectif contractuel saisi ou cible commune)."""
    decided = set(decided)
    reach = [sid for sid in prep.slots if sid in decided or not _counts(prep, prep.slots[sid])]
    ids = list(prep.emps)
    explicit = prep.fair_explicit
    pool = [i for i in ids if i not in explicit and prep.fair_cap.get(i, 0) > 0]
    levels = shared_fill({sid: prep.slots[sid].effective_minutes for sid in reach}, prep.by_emp, prep.fair_cap, pool,
                         {i: explicit[i] for i in ids if i in explicit}, supply=supply, weeks=prep.fair_weeks, days=prep.fair_days)
    common = max((levels.get(i, 0) for i in pool), default=0)
    targets = {i: explicit.get(i, levels.get(i, 0)) for i in ids}
    refs = {i: (prep.fair_contract[i] if i in explicit else (common if i in pool else 0)) for i in ids}
    return targets, refs


def shared_fill(slot_minutes: Dict[str, int], usual: Dict[str, List[Slot]], caps: Dict[str, int], pool: List[str], fixed: Dict[str, int],
                step: int = 30, supply: Optional[int] = None, weeks: Optional[Dict[str, Dict[tuple, int]]] = None,
                days: Optional[Dict[str, Dict[date, int]]] = None) -> Dict[str, int]:
    """Répartition max-min des heures par flot : on élève un niveau commun L pour tous ; chacun reçoit min(capacité, L) tant que les shifts
    réellement retenus le permettent (un shift par jour, limites hebdomadaires de jours et d'heures, shifts autorisés). Quand
    un groupe de collaborateurs qui se partagent les mêmes shifts est saturé, ses membres sont arrêtés à leur part de ce groupe et les autres
    continuent de monter. Les objectifs contractuels explicites (`fixed`) sont servis d'abord. `supply` borne le total des cibles (volume
    décidé) quand les shifts atteignables le dépassent. Résultat au pas de `step` minutes."""
    from ortools.graph.python import max_flow

    slots = list(slot_minutes)
    sidx = {sid: k for k, sid in enumerate(slots)}
    who = list(fixed) + [i for i in pool if i not in fixed]
    on_days = {i: sorted({s.day for s in usual.get(i, ()) if s.id in sidx}) for i in who}
    # nœuds : 0 source, 1 puits, collaborateurs, (collaborateur, semaine), (collaborateur, jour), shifts
    node, nxt = {}, 2
    for i in who:
        node[i] = nxt; nxt += 1
        for d in on_days[i]:
            wkey = d.isocalendar()[:2]
            if (i, wkey) not in node:
                node[i, wkey] = nxt; nxt += 1
            node[(i, d)] = nxt; nxt += 1
    base = nxt
    arcs = []
    for i in who:
        per_day: Dict[date, int] = defaultdict(int)
        for s in usual.get(i, ()):
            if s.id in sidx:
                per_day[s.day] = max(per_day[s.day], s.effective_minutes)
                arcs.append((node[(i, s.day)], base + sidx[s.id], s.effective_minutes))
        per_week: Dict[tuple, int] = defaultdict(int)
        for d, mi in per_day.items():
            cap_d = min(mi, (days or {}).get(i, {}).get(d, mi))
            arcs.append((node[i, d.isocalendar()[:2]], node[(i, d)], cap_d))
            per_week[d.isocalendar()[:2]] += cap_d
        for wkey, tot in per_week.items():
            arcs.append((node[i], node[i, wkey], min(tot, (weeks or {}).get(i, {}).get(wkey, tot))))
    g = max_flow.SimpleMaxFlow()  # graphe construit une fois ; seules les demandes (arcs depuis la source) changent ensuite
    src = {i: g.add_arc_with_capacity(0, node[i], 0) for i in who}
    for a, b, c in arcs:
        g.add_arc_with_capacity(a, b, c)
    for k, sid in enumerate(slots):
        g.add_arc_with_capacity(base + k, 1, slot_minutes[sid])

    def served(demand: Dict[str, int]) -> int:
        for i in who:
            g.set_arc_capacity(src[i], max(0, demand.get(i, 0)))
        return g.optimal_flow() if g.solve(0, 1) == g.OPTIMAL else 0

    # objectifs explicites d'abord ; s'ils ne peuvent pas tous être servis, réduits ensemble (même règle de remplissage)
    done: Dict[str, int] = {}
    if fixed:
        lo, hi = 0, max(fixed.values())
        while lo < hi:
            mid = (lo + hi + 1) // 2
            dem = {i: min(v, mid) for i, v in fixed.items()}
            lo, hi = (mid, hi) if (supply is None or sum(dem.values()) <= supply) and served(dem) == sum(dem.values()) else (lo, mid - 1)
        done = {i: min(v, lo) for i, v in fixed.items()}
    active = [i for i in pool if i not in fixed and caps.get(i, 0) > 0]
    level = 0
    while active:
        def ok(L: int, extra: Optional[str] = None) -> bool:
            dem = {**done, **{i: min(caps[i], L) for i in active}}
            if extra is not None:
                dem[extra] = min(caps[extra], L + step)
            total = sum(dem.values())
            return (supply is None or total <= supply) and served(dem) == total
        lo, hi = 0, -(-(max(caps[i] for i in active) - level) // step)
        while lo < hi:  # niveau commun le plus haut atteignable par tous les collaborateurs encore actifs (pas de `step` minutes)
            mid = (lo + hi + 1) // 2
            lo, hi = (mid, hi) if ok(level + mid * step) else (lo, mid - 1)
        level += lo * step
        stuck = [i for i in active if caps[i] <= level or not ok(level, i)]
        if not stuck:  # ne devrait pas arriver : sécurité contre une boucle infinie
            stuck = list(active)
        for i in stuck:
            done[i] = min(caps[i], level)
        active = [i for i in active if i not in stuck]
    return done


def water_fill(supply: int, refs: Dict[str, int], caps: Dict[str, int]) -> Dict[str, int]:
    """Remplissage : la même proportion λ de sa référence pour chacun (références égales : les mêmes heures pour tous), sans dépasser sa
    capacité ; l'excédent de ceux qui sont limités revient aux autres (répartition max-min). Total = min(offre, somme des capacités)."""
    ids = [i for i in refs if refs[i] > 0 and caps.get(i, 0) > 0]
    if not ids:
        return {i: 0 for i in refs}
    lo, hi = 0.0, max(caps[i] / refs[i] for i in ids)
    for _ in range(60):
        mid = (lo + hi) / 2
        if sum(min(caps[i], mid * refs[i]) for i in ids) < supply:
            lo = mid
        else:
            hi = mid
    out = {i: 0 for i in refs}
    for i in ids:
        out[i] = int(min(caps[i], hi * refs[i]))
    return out


def individual_penalty(prep: Prepared, e: Employee) -> int:
    return round(10 * (1 - e.weight / prep.wmax)) if prep.wmax > 0 else 0


def cost_units(e: Employee, s: Slot) -> int:
    """Coût estimé d'un shift en francs (arrondi), uniquement si le coût horaire du contrat est renseigné (jamais supposé)."""
    c = e.contract
    if c is None or c.hourly_cost_cents is None:
        return 0
    return round(s.effective_minutes * c.hourly_cost_cents / 6000)
