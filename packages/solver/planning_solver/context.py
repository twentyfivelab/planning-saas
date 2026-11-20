"""Préparation commune au moteur CP-SAT, à l'évaluateur de la fonction objectif, au classement des remplaçants et aux
explications : éligibilité (préfiltrage des affectations impossibles), cibles d'équité, catégories horaires… Un seul calcul,
partagé, pour que le moteur et les outils d'analyse appliquent exactement les mêmes règles."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Dict, List, Optional, Set, Tuple

from .model import REINFORCE, Employee, Slot, SolverInput, site_start_times, slot_category
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
    targets: Dict[str, int]  # part équitable (minutes) par collaborateur, pour l'affichage et les explications
    fair_ref: Dict[str, int]  # référence d'équité (minutes) : objectif contractuel explicite, sinon la cible commune de l'équipe
    fair_cap: Dict[str, int]  # charge maximale atteignable (minutes) : un shift par jour, limites de jours, plafond mensuel
    fair_explicit: Dict[str, int]  # objectif contractuel explicite, plafonné par la capacité
    fair_contract: Dict[str, int]  # objectif contractuel tel que saisi
    budgeted_brands: Set[str]  # marques ayant un budget ce mois (leurs besoins optionnels comptent dans le volume visé)
    wmax: float
    category: Dict[str, Optional[str]] = field(default_factory=dict)  # slot -> matin | middle | soir | None
    # mois civils de la période -> jours ; jours et minutes déjà travaillés hors période dans ces mêmes mois (périodes voisines)
    months: Dict[Tuple[int, int], List[date]] = field(default_factory=dict)
    outside_month_days: Dict[Tuple[str, Tuple[int, int]], Set[date]] = field(default_factory=dict)
    outside_month_minutes: Dict[Tuple[str, Tuple[int, int]], int] = field(default_factory=dict)

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
    # Équité : CIBLE COMMUNE d'heures mensuelles pour tous, plafonnée par ce que chacun peut réellement atteindre (un shift par jour sur les
    # jours où il peut travailler, jours maximum, plafond mensuel), et remplacée par l'objectif contractuel explicite quand il existe
    # (lui aussi plafonné). Le volume restant est réparti à parts égales entre les autres (remplissage : l'excédent de ceux qui sont
    # limités revient aux autres). Jamais le poids d'allocation : ni ancienneté ni mérite ne créent de priorité automatique.
    supply = sum(s.effective_minutes for s in inp.slots if s.mandatory)
    supply += sum(b.target_minutes for b in inp.budgets if b.brand in optional_brands)
    caps: Dict[str, int] = {}
    explicit: Dict[str, int] = {}
    for e in inp.employees:
        c = e.contract
        # habilitations : les shifts où il n'est qu'en renfort (dernier recours par définition) ne comptent pas dans sa capacité attendue
        usual = [s for s in by_emp[e.id] if not all(e.brands.get(b) == REINFORCE for b in s.brands)]
        caps[e.id] = max_load_minutes(usual, e)
        if inp.config.monthly_cap_minutes is not None:  # jamais au-delà du plafond mensuel de l'entreprise
            caps[e.id] = min(caps[e.id], sum(max(0, inp.config.monthly_cap_minutes - o_min.get((e.id, k), 0)) for k in months))
        if c and c.monthly_target_minutes:
            explicit[e.id] = min(c.monthly_target_minutes, caps[e.id])
    contract = {e.id: e.contract.monthly_target_minutes for e in inp.employees if e.id in explicit}
    # estimation initiale (avant calcul) : besoins obligatoires + budgets ; le moteur la remplace par le volume réellement décidé
    targets, refs = common_targets(supply, caps, explicit, contract, [e.id for e in inp.employees])
    return Prepared(inp=inp, slots={s.id: s for s in inp.slots}, emps={e.id: e for e in inp.employees}, days=days,
                    starts_by_site=starts_by_site, outside=dict(outside), by_emp=by_emp, eligible=eligible, suns=sundays_in(inp),
                    optional_brands=optional_brands, targets=targets, fair_ref=refs, fair_cap=caps, fair_explicit=explicit, fair_contract=contract,
                    budgeted_brands={b.brand for b in inp.budgets}, wmax=max((e.weight for e in inp.employees), default=0),
                    category={s.id: slot_category(s, starts_by_site) for s in inp.slots}, months=dict(months),
                    outside_month_days=dict(o_days), outside_month_minutes=dict(o_min))


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
        if mentors:
            out.append(("mentor", e, sorted({r.other for r in mentors}), any(r.strict for r in mentors), "site_day"))
        for r in e.relations:
            if r.kind in ("avoid_together", "work_together") and r.other in prep.emps and r.other != e.id:
                if e.id < r.other or not any(x.kind == r.kind and x.other == e.id for x in prep.emps[r.other].relations):
                    scope = r.scope if r.kind == "avoid_together" else "site_day"
                    out.append((r.kind, e, [r.other], r.strict and r.kind == "avoid_together", scope))
    return out


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


def max_load_minutes(slots, e) -> int:
    """Charge maximale atteignable : un shift par jour (le plus long éligible), limites de jours par semaine ou par mois."""
    per_day: Dict[date, int] = {}
    for s in slots:
        per_day[s.day] = max(per_day.get(s.day, 0), s.effective_minutes)
    if e.max_days_count and e.max_days_period == "week":
        weeks: Dict[tuple, List[int]] = defaultdict(list)
        for d, mi in per_day.items():
            weeks[d.isocalendar()[:2]].append(mi)
        vals = [x for v in weeks.values() for x in sorted(v, reverse=True)[: e.max_days_count]]
    else:
        vals = list(per_day.values())
    vals.sort(reverse=True)
    lims = [x for x in (e.max_days_month, e.max_days_count if e.max_days_period == "month" else None) if x]
    return sum(vals[: min(lims)] if lims else vals)


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
    """Cibles calculées sur le volume réellement décidé (et non sur le volume promis par les budgets, parfois inatteignable), plafonnées
    par ce que chacun peut réellement atteindre COMPTE TENU DES AUTRES : des collaborateurs qui se partagent les mêmes shifts habituels
    ne peuvent pas tous atteindre la cible commune si leurs shifts n'y suffisent pas (remplissage max-min par flot, `shared_fill`)."""
    def counts(s):
        return s.mandatory or any(b in prep.budgeted_brands for b in s.brands)
    counted = [sid for sid in slot_ids if (s := prep.slots.get(sid)) is not None and counts(s)]
    # shifts atteignables : ceux du volume décidé, plus les besoins optionnels sans budget (pas de volume visé : le moteur peut en
    # retenir pour rapprocher chacun de la cible) ; le total des cibles reste borné par le volume décidé
    reach = counted + [s.id for s in prep.slots.values() if not counts(s)]
    ids = list(prep.emps)
    explicit = prep.fair_explicit
    pool = [i for i in ids if i not in explicit and prep.fair_cap.get(i, 0) > 0]
    levels = shared_fill({sid: prep.slots[sid].effective_minutes for sid in reach}, prep.by_emp, prep.fair_cap, pool,
                         {i: explicit[i] for i in ids if i in explicit}, supply=sum(prep.slots[sid].effective_minutes for sid in counted))
    common = max((levels.get(i, 0) for i in pool), default=0)
    targets = {i: explicit.get(i, levels.get(i, 0)) for i in ids}
    refs = {i: (prep.fair_contract[i] if i in explicit else (common if i in pool else 0)) for i in ids}
    return targets, refs


def shared_fill(slot_minutes: Dict[str, int], usual: Dict[str, List[Slot]], caps: Dict[str, int], pool: List[str], fixed: Dict[str, int],
                step: int = 30, supply: Optional[int] = None) -> Dict[str, int]:
    """Répartition max-min des heures par flot : on élève un niveau commun L pour tous ; chacun reçoit min(capacité, L) tant que les shifts
    réellement retenus le permettent (un shift par jour, uniquement sur ses shifts habituels — le renfort reste un dernier recours). Quand
    un groupe de collaborateurs qui se partagent les mêmes shifts est saturé, ses membres sont arrêtés à leur part de ce groupe et les autres
    continuent de monter. Les objectifs contractuels explicites (`fixed`) sont servis d'abord. `supply` borne le total des cibles (volume
    décidé) quand les shifts atteignables le dépassent. Résultat au pas de `step` minutes."""
    from ortools.graph.python import max_flow

    slots = list(slot_minutes)
    sidx = {sid: k for k, sid in enumerate(slots)}
    who = list(fixed) + [i for i in pool if i not in fixed]
    days = {i: sorted({s.day for s in usual.get(i, ()) if s.id in sidx}) for i in who}
    # nœuds : 0 source, 1 puits, collaborateurs, (collaborateur, jour), shifts
    node, nxt = {}, 2
    for i in who:
        node[i] = nxt; nxt += 1
        for d in days[i]:
            node[(i, d)] = nxt; nxt += 1
    base = nxt
    arcs = []
    for i in who:
        per_day: Dict[date, int] = defaultdict(int)
        for s in usual.get(i, ()):
            if s.id in sidx:
                per_day[s.day] = max(per_day[s.day], s.effective_minutes)
                arcs.append((node[(i, s.day)], base + sidx[s.id], s.effective_minutes))
        for d, mi in per_day.items():
            arcs.append((node[i], node[(i, d)], mi))
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
