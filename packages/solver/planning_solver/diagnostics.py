"""Données manquantes et diagnostics exploitables (jamais un simple « aucun planning »)."""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, List

from .model import Issue, SolverInput


NON_EXECUTED_LEGAL_RULES = (
    "pauses légales", "durée maximale du travail (journalière/hebdomadaire)", "travail de nuit", "travail du dimanche",
    "jeunes travailleurs", "catégories particulières de travailleurs", "dérogations conventionnelles")


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
    out.append(Issue("LEGAL_REVIEW", "warning",
                     "Seuls le repos quotidien (défaut 11 h) et le maximum de jours consécutifs (défaut 6) sont "
                     "exécutés, comme valeurs de référence NON validées juridiquement. Non exécutées : " +
                     ", ".join(NON_EXECUTED_LEGAL_RULES) + ". Non commercialisable / non utilisable en production "
                     "tant que ces règles ne sont pas exécutées et validées par un spécialiste du droit suisse.",
                     constraints=["règles légales non exécutées"]))
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
