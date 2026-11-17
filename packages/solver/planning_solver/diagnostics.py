"""Données manquantes et diagnostics exploitables (jamais un simple « aucun planning »)."""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from typing import Dict, List

from .model import Issue, SolverInput, fmt_minutes, month_label, site_start_times, slot_category
from .sundays import sunday_summary, sundays_in


NON_EXECUTED_LEGAL_RULES = (
    "travail de nuit", "travail du dimanche et repos compensatoires", "jeunes travailleurs", "catégories particulières de travailleurs", "dérogations conventionnelles")


def missing_data(inp: SolverInput) -> List[Issue]:
    out: List[Issue] = []
    no_contract = [e.name for e in inp.employees if e.contract is None]
    if no_contract:
        out.append(Issue(
            "CONTRACT_MISSING", "warning",
            f"Contrat non renseigné pour {len(no_contract)} collaborateur(s) : {', '.join(no_contract)}. "
            "Aucun taux d'activité ni plafond n'est supposé ; le résultat est une simulation exploratoire.",
            constraints=["plafonds contractuels"],
            suggestions=["Saisir date de début/fin, taux d'activité, heures min/max et heures supplémentaires."]))
    no_avail = [e.name for e in inp.employees if e.available_weekdays is None]
    if no_avail:
        out.append(Issue(
            "AVAILABILITY_INCOMPLETE", "warning",
            f"Disponibilités non déclarées (considérées ouvertes hors indisponibilités connues) pour : "
            f"{', '.join(no_avail)}.",
            suggestions=["Renseigner les disponibilités complètes de chaque collaborateur."]))
    if not inp.leaves_provided:
        out.append(Issue("LEAVES_MISSING", "warning",
                         "Aucun congé ni absence saisi pour la période.",
                         suggestions=["Importer ou saisir les congés et absences."]))
    for b in inp.budgets:
        if not b.requirements_defined:
            out.append(Issue(
                "BRAND_REQUIREMENTS_MISSING", "blocking",
                f"{b.brand} : budget de {b.target_minutes / 60:g} h sans jours ni horaires définis. "
                "Ces heures ne peuvent pas être planifiées définitivement (rien n'a été inventé).",
                constraints=[f"besoins journaliers {b.brand}"],
                suggestions=[f"Renseigner les jours et horaires de {b.brand} (besoins journaliers)."]))
    # semaines à cheval sur deux périodes : limites hebdomadaires partielles sans historique voisin
    boundary = []
    d0, d1 = inp.period_start, inp.period_end
    if d0.weekday() != 0:
        boundary.append(f"semaine du {d0 - timedelta(days=d0.weekday()):%d/%m}")
    if d1.weekday() != 6:
        boundary.append(f"semaine du {d1 - timedelta(days=d1.weekday()):%d/%m}")
    limited = [e.name for e in inp.employees if e.max_days_per_week is not None or (e.max_days_count is not None and e.max_days_period == "week")]
    if boundary and limited and not inp.history_provided:
        out.append(Issue(
            "WEEK_BOUNDARY_HISTORY_MISSING", "warning",
            f"Limites hebdomadaires de jours ({', '.join(limited)}) : les {' et '.join(boundary)} chevauchent une autre période et aucun planning voisin n'est fourni ; "
            "seuls les jours de la période sont comptés (jours hors période non supposés).",
            suggestions=["Créer ou importer le planning de la période voisine pour que ses jours soient comptés."]))
    budgeted = {b.brand for b in inp.budgets}
    unbudgeted = sorted({b for s in inp.slots for b in s.brands} - budgeted)
    for b in unbudgeted:
        out.append(Issue("BRAND_BUDGET_MISSING", "warning",
                         f"{b} : shifts planifiés sans budget horaire saisi ; ses heures ne sont comptées dans aucun budget (rien n'a été supposé).",
                         suggestions=[f"Saisir le budget mensuel de {b} et ses besoins hors des jours déjà définis."]))
    sun = sunday_summary(inp)
    if sundays_in(inp):
        for al in sun["alerts"]:
            out.append(Issue("SUNDAY_QUOTAS", "warning" if al["level"] == "warning" else "info", al["text"]))
    executed = ["repos quotidien", "jours consécutifs"]
    pending = list(NON_EXECUTED_LEGAL_RULES)
    if inp.config.break_rules:
        executed.append("pauses")
    else:
        pending.insert(0, "pauses légales (règle à activer dans le référentiel juridique)")
    if any(e.legal_weekly_max_minutes is not None for e in inp.employees):
        executed.append("durée maximale hebdomadaire")
    else:
        pending.insert(0, "durée maximale hebdomadaire (règle à activer dans le référentiel juridique)")
    out.append(Issue("LEGAL_REVIEW", "warning",
                     "Règles exécutées, comme valeurs de référence à faire valider : " + ", ".join(executed) + ". Non exécutées : " +
                     ", ".join(pending) + ". Non commercialisable / non utilisable en production "
                     "tant que ces règles ne sont pas exécutées et validées par un spécialiste du droit suisse.",
                     constraints=["règles légales non exécutées"]))
    rules = inp.config.break_rules
    short = [s.id for s in inp.slots if s.break_minutes < max((b for over, b in rules if s.effective_minutes > over), default=0)]
    if short:
        out.append(Issue("BREAK_RULE", "blocking", f"{len(short)} shift(s) ont une pause inférieure au référentiel juridique activé : ils ne seront pas pourvus tant que l'horaire n'est pas corrigé.",
                         slots=short[:50], constraints=["pauses"], suggestions=["Corriger la pause du modèle de shift ou la règle du référentiel juridique."]))
    for h in inp.hypotheses:
        out.append(Issue("HYPOTHESIS", "warning", h,
                         suggestions=["Confirmer l'horaire avec le client ou le corriger dans les modèles de shifts."]))
    return out


def _candidates(inp: SolverInput, slot) -> Dict[str, List[str]]:
    """Employés éliminés à chaque étape de filtrage pour un slot."""
    stages: Dict[str, List[str]] = defaultdict(list)
    for e in inp.employees:
        if any(b not in e.brands for b in slot.brands):
            stages["marque non éligible"].append(e.name)
        elif any(k not in e.skills for k in slot.required_skills):
            stages["qualification manquante"].append(e.name)
        elif e.blocked(slot.day):
            stages["indisponible / absent"].append(e.name)
        elif slot.tag in e.forbidden_tags:
            stages["règle dure individuelle (shift interdit)"].append(e.name)
        elif e.sunday_quota == 0 and slot.day.weekday() == 6:
            stages["quota de 0 dimanche"].append(e.name)
        elif e.time_pref and e.time_pref_strict and (
                slot_category(slot, site_start_times(inp)) not in (None, e.time_pref)):
            stages["préférence horaire stricte"].append(e.name)
        else:
            stages["candidat"].append(e.name)
    return stages


def diagnose_uncovered(inp: SolverInput, slot_ids: List[str], locked: Dict[str, str]) -> List[Issue]:
    slots = {s.id: s for s in inp.slots}
    out: List[Issue] = []
    combos: List[str] = []
    for sid in slot_ids:
        s = slots[sid]
        st = _candidates(inp, s)
        if not st.get("candidat"):
            causes = {k: v for k, v in st.items() if k != "candidat"}
            main = max(causes, key=lambda k: len(causes[k])) if causes else "aucun collaborateur"
            out.append(Issue(
                "NO_CANDIDATE", "blocking",
                f"{sid} ({s.day}, {s.start:%H:%M}-{s.end:%H:%M}, {'/'.join(s.brands)}) : aucun candidat. "
                f"Cause principale : {main}.",
                slots=[sid], constraints=sorted(causes),
                suggestions=["Étendre l'éligibilité marque/qualifications, lever une indisponibilité, "
                             "ou renforcer l'équipe."]))
        else:
            combos.append(sid)
    if combos:
        out.append(Issue(
            "COMBINED_CONSTRAINTS", "warning",
            f"{len(combos)} shift(s) non couvert(s) alors que des candidats existent : conflits entre repos de "
            f"{inp.config.rest_hours} h, {inp.config.max_consecutive_days} jours consécutifs max, plafonds "
            "hebdomadaires et autres couvertures.",
            slots=combos,
            constraints=["repos quotidien", "jours consécutifs", "plafonds hebdomadaires/contractuels"],
            suggestions=["Ajouter des renforts éligibles.", "Réduire ou décaler les besoins sur ces shifts.",
                         "Demander une dérogation légale documentée (rôle autorisé, motif obligatoire).",
                         "Relâcher une préférence marquée comme contrainte dure (ex. jours de repos)."]))
    return out


def core_issue(inp: SolverInput, solver, assump: dict) -> Issue:
    idx = set(solver.SufficientAssumptionsForInfeasibility())
    names = [sid for sid, lit in assump.items() if lit.Index() in idx]
    return Issue(
        "INFEASIBLE_CORE", "blocking",
        "Couverture stricte impossible : ces besoins sont mutuellement incompatibles avec les contraintes dures "
        f"({len(names)} shift(s) dans le noyau minimal).",
        slots=names, constraints=["couverture stricte", "contraintes dures"],
        suggestions=["Passer en couverture partielle pour obtenir un planning avec les manques listés.",
                     "Retirer un des shifts du noyau ou ajouter des collaborateurs éligibles."])


def _max_days_with_streak(days: List, possible: set, limit: int) -> int:
    """Nombre maximal de jours travaillables parmi `possible` sans dépasser `limit` jours consécutifs (glouton optimal)."""
    n, run = 0, 0
    for d in days:
        if d in possible and run < limit:
            n, run = n + 1, run + 1
        else:  # jour impossible, ou série pleine : repos forcé
            run = 0
    return n


def min_days_reasons(prep, e, key) -> List[str]:
    """Raisons EXACTES pour lesquelles le minimum de jours de `e` est impossible sur le mois `key` (liste vide = pas impossible à lui seul)."""
    from .context import min_days_need
    cfg = prep.inp.config
    need = min_days_need(prep, e, key)
    if not need:
        return []
    done_out = e.min_days_month - need
    mdays = prep.months.get(key, [])
    mine = [s for s in prep.by_emp.get(e.id, ()) if (s.day.year, s.day.month) == key]
    possible = sorted({s.day for s in mine})
    reasons: List[str] = []
    if len(possible) < need:
        reasons.append(f"seulement {len(possible) + done_out} jour(s) possible(s) ce mois-ci compte tenu de ses disponibilités, indisponibilités, "
                       "jours de repos, marques et sites autorisés et des shifts prévus")
    if e.max_days_month is not None and e.max_days_month < e.min_days_month:
        reasons.append(f"son maximum de {e.max_days_month} jours par mois est inférieur au minimum")
    if cfg.monthly_cap_minutes is not None and possible:
        room = cfg.monthly_cap_minutes - prep.outside_month_minutes.get((e.id, key), 0)
        shortest = sorted(min(s.effective_minutes for s in mine if s.day == d) for d in possible)
        k, acc = 0, 0
        for mins in shortest:
            if acc + mins > room:
                break
            acc, k = acc + mins, k + 1
        if k < need:
            reasons.append(f"le plafond mensuel de {fmt_minutes(cfg.monthly_cap_minutes)} ne permet que {k + done_out} jour(s) avec les shifts "
                           f"possibles (au moins {fmt_minutes(shortest[0])} de travail effectif chacun)")
    week_cap = e.max_days_per_week
    if e.max_days_count is not None and e.max_days_period == "week":
        week_cap = e.max_days_count if week_cap is None else min(week_cap, e.max_days_count)
    if week_cap is not None and possible:
        weeks: Dict[tuple, int] = defaultdict(int)
        for d in possible:
            weeks[d.isocalendar()[:2]] += 1
        bound = sum(min(week_cap, n) for n in weeks.values())
        if bound < need:
            reasons.append(f"la limite de {week_cap} jour(s) par semaine ne permet que {bound + done_out} jour(s) ce mois-ci")
    if possible:
        streak = _max_days_with_streak(mdays, set(possible), cfg.max_consecutive_days)
        if streak < need and len(possible) >= need:
            reasons.append(f"le maximum de {cfg.max_consecutive_days} jours consécutifs ne permet que {streak + done_out} jour(s) ce mois-ci")
    return reasons


def min_days_blockers(prep) -> List[Issue]:
    """Minimums de jours impossibles à respecter, détectés AVANT le calcul : un diagnostic bloquant par collaborateur et par mois."""
    out: List[Issue] = []
    for e in prep.inp.employees:
        if not e.min_days_month or e.excluded or e.left_on is not None:
            continue
        for key in prep.months:
            reasons = min_days_reasons(prep, e, key)
            if reasons:
                out.append(Issue(
                    "MIN_DAYS_IMPOSSIBLE", "blocking",
                    f"Minimum de jours impossible pour {e.name} en {month_label(*key)} : {e.min_days_month} jours demandés, mais "
                    + " ; ".join(reasons) + ".",
                    constraints=["minimum de jours travaillés par mois"], employee=e.id,
                    suggestions=["Réduire le minimum de jours (ou choisir « Pas de préférence ») pour ce mois.",
                                 "Élargir ses disponibilités, marques ou sites autorisés, ou ajouter des besoins compatibles."]))
    return out


def _group_day_bound(by_day: List[Dict[object, set]], members: List[int]) -> int:
    """Majorant EXACT du nombre total de jours travaillés par un groupe : chaque jour, au plus un shift par collaborateur et un
    collaborateur par shift, soit min(shifts admissibles pour le groupe, collaborateurs admissibles) jour par jour."""
    days = set().union(*(by_day[i].keys() for i in members))
    total = 0
    for d in days:
        present = [i for i in members if d in by_day[i]]
        total += min(len(set().union(*(by_day[i][d] for i in present))), len(present))
    return total


def min_days_group_conflicts(prep) -> List[Issue]:
    """Minimums de jours possibles un à un mais incompatibles ENSEMBLE parce que plusieurs collaborateurs se partagent les mêmes shifts,
    détectés AVANT le calcul par simple dénombrement : résultat identique quelle que soit la charge de la machine ou la durée accordée.
    Seuls les cas certains sont signalés (majorant exact) ; les conflits plus subtils restent identifiés par le noyau du solveur."""
    from .context import min_days_need
    out: List[Issue] = []
    for key in prep.months:
        group = []
        for e in prep.inp.employees:
            if not e.min_days_month or e.excluded or e.left_on is not None:
                continue
            need = min_days_need(prep, e, key)
            if not need or min_days_reasons(prep, e, key):
                continue  # pas de minimum à atteindre, ou déjà signalé seul (MIN_DAYS_IMPOSSIBLE)
            days: Dict[object, set] = defaultdict(set)
            for s in prep.by_emp.get(e.id, ()):
                if (s.day.year, s.day.month) == key:
                    days[s.day].add(s.id)
            group.append((e, need, days))
        if len(group) < 2:
            continue
        by_day = [g[2] for g in group]
        slots_of = [set().union(*d.values()) if d else set() for d in by_day]
        flagged: set = set()
        for i in range(len(group)):  # paires d'abord : la cause la plus simple à corriger
            for j in range(i + 1, len(group)):
                if not slots_of[i] & slots_of[j]:
                    continue  # aucun shift en commun : les deux minimums sont indépendants
                bound = _group_day_bound(by_day, [i, j])
                if group[i][1] + group[j][1] > bound:
                    out.append(_group_issue([group[i], group[j]], key, bound))
                    flagged |= {i, j}
        # groupes plus larges : collaborateurs reliés par des shifts communs (composantes), si aucune paire n'explique déjà le conflit
        seen: set = set()
        for i in range(len(group)):
            if i in seen:
                continue
            comp, todo = [], [i]
            while todo:
                k = todo.pop()
                if k in seen:
                    continue
                seen.add(k)
                comp.append(k)
                todo += [j for j in range(len(group)) if j not in seen and slots_of[k] & slots_of[j]]
            if len(comp) > 2 and not flagged & set(comp):
                bound = _group_day_bound(by_day, comp)
                if sum(group[k][1] for k in comp) > bound:
                    out.append(_group_issue([group[k] for k in sorted(comp)], key, bound))
    return out


def _group_issue(members: List[tuple], key, bound: int) -> Issue:
    names = ", ".join(f"{e.name} ({e.min_days_month} jours en {month_label(*key)})" for e, _n, _d in members)
    need = sum(n for _e, n, _d in members)
    done = sum(e.min_days_month - n for e, n, _d in members)
    total = f"{need} jours" + (f" à travailler dans ce planning, {done} déjà travaillés ailleurs dans le mois" if done else "")
    return Issue("MIN_DAYS_CONFLICT", "blocking",
                 f"Minimum de jours impossible à respecter pour {names} : leurs minimums cumulés ({total}) dépassent les {bound} shifts "
                 "qu'ils peuvent occuper (un jour compte une fois par collaborateur et chaque shift n'est tenu que par une personne).",
                 constraints=["minimum de jours travaillés par mois"], employee=members[0][0].id if len(members) == 1 else None,
                 suggestions=["Réduire l'un de ces minimums (ou « Pas de préférence ») pour ce mois.", "Ajouter des besoins ou des collaborateurs compatibles."])


def min_days_core_issue(prep, core: List[tuple]) -> Issue:
    """Minimums de jours compatibles un à un mais incompatibles ENSEMBLE avec les autres contraintes obligatoires (noyau du solveur)."""
    emps = prep.emps
    who = [(emps[eid], key) for eid, key in core if eid in emps]
    names = ", ".join(f"{e.name} ({e.min_days_month} jours en {month_label(*k)})" for e, k in who)
    detail = ""
    if len(who) > 1:
        slots = {s.id for e, k in who for s in prep.by_emp.get(e.id, ()) if (s.day.year, s.day.month) == k}
        total = sum(e.min_days_month for e, _k in who)
        if total > len(slots):
            detail = f" : leurs minimums cumulés ({total} jours) dépassent les {len(slots)} shifts qu'ils peuvent occuper"
    if not detail:
        cfg = prep.inp.config
        detail = (f" avec les autres contraintes obligatoires (repos quotidien de {cfg.rest_hours} h, {cfg.max_consecutive_days} jours consécutifs au "
                  "plus, plafonds d'heures, budgets stricts, relations entre collaborateurs, affectations verrouillées)")
    return Issue("MIN_DAYS_CONFLICT", "blocking", f"Minimum de jours impossible à respecter pour {names}{detail}.",
                 constraints=["minimum de jours travaillés par mois"], employee=who[0][0].id if len(who) == 1 else None,
                 suggestions=["Réduire l'un de ces minimums (ou « Pas de préférence ») pour ce mois.", "Ajouter des besoins ou des collaborateurs compatibles."])


def pre_generation_checks(prep) -> List[Issue]:
    """Incohérences évidentes AVANT génération (bornes exactes ou majorantes, jamais une estimation optimiste) :
    créneaux obligatoires sans aucun collaborateur admissible, capacité maximale de l'effectif inférieure aux besoins, budget strict
    inférieur aux besoins obligatoires de la marque."""
    inp = prep.inp
    cfg = inp.config
    out: List[Issue] = []
    mandatory = [s for s in inp.slots if s.mandatory]
    eligible_slots = {sid for _eid, sid in prep.eligible}
    orphans = [s for s in mandatory if s.id not in eligible_slots]
    if orphans:
        ex = ", ".join(f"{s.day:%d/%m} {s.start:%H:%M}–{s.end:%H:%M} {s.site} ({'/'.join(s.brands)})" for s in orphans[:5])
        out.append(Issue("NO_ELIGIBLE_EMPLOYEE", "warning",
                         f"{len(orphans)} shift(s) obligatoire(s) sans aucun collaborateur admissible (marque, site, qualification, disponibilité, "
                         f"effectif du mois) : {ex}{' …' if len(orphans) > 5 else ''}. Ils resteront non couverts.",
                         slots=[s.id for s in orphans], suggestions=["Autoriser un collaborateur sur cette marque ou ce site, ou revoir le besoin."]))
    demand = sum(s.effective_minutes for s in mandatory)
    capacity = 0
    for e in inp.employees:
        mine = prep.by_emp.get(e.id, [])
        if not mine:
            continue
        best: Dict[object, int] = {}
        for s in mine:  # un shift par jour au plus pour le majorant (repos quotidien)
            best[s.day] = max(best.get(s.day, 0), s.effective_minutes)
        days = sorted(best.values(), reverse=True)
        if e.max_days_month is not None:
            days = days[:e.max_days_month * max(1, len(prep.months))]
        cap = sum(days)
        if cfg.monthly_cap_minutes is not None:
            cap = min(cap, cfg.monthly_cap_minutes * max(1, len(prep.months)))
        if e.contract and e.contract.monthly_max_minutes is not None and not e.contract.overtime_allowed:
            cap = min(cap, e.contract.monthly_max_minutes)
        capacity += cap
    if demand and capacity < demand:
        out.append(Issue("CAPACITY_BELOW_DEMAND", "warning",
                         f"Capacité maximale de l'effectif : {fmt_minutes(capacity)} pour {fmt_minutes(demand)} de besoins obligatoires. "
                         f"Au moins {fmt_minutes(demand - capacity)} resteront non couvertes, quelle que soit l'optimisation.",
                         suggestions=["Ajouter des collaborateurs ou des autorisations de marque.", "Réduire les besoins du mois."]))
    need_by_brand: Dict[str, int] = defaultdict(int)
    for s in mandatory:
        for b, mi in s.allocations.items():
            need_by_brand[b] += mi
    for b in inp.budgets:
        if b.strict and need_by_brand.get(b.brand, 0) > b.target_minutes:
            gap = need_by_brand[b.brand] - b.target_minutes
            out.append(Issue("BUDGET_BELOW_DEMAND", "warning",
                             f"{b.brand} : budget strict de {fmt_minutes(b.target_minutes)} pour {fmt_minutes(need_by_brand[b.brand])} de besoins obligatoires. "
                             f"{fmt_minutes(gap)} ne pourront pas être couvertes sans dépasser le budget.",
                             suggestions=["Augmenter le budget du mois, le rendre non strict, ou réduire les besoins."]))
    return out
