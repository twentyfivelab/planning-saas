"""Pondérations personnalisables de l'algorithme.

L'utilisateur règle des critères sur une échelle 0–100 ; chaque critère agit sur un ou plusieurs poids réels de la fonction
d'optimisation. Poids du moteur = poids par défaut × 2 ** ((valeur − valeur par défaut) / 20) : +20 points doublent
l'influence du critère, −20 la divisent par deux, 0 la supprime. Les contraintes strictes (chevauchement, repos, jours
consécutifs, indisponibilités, marques autorisées, verrous, budgets stricts…) ne dépendent JAMAIS de ces poids.
"""
from typing import Dict, List, Optional, Tuple

from .model import DEFAULT_WEIGHTS

# clé, libellé, valeur indicative par défaut, poids du moteur concernés, explication
CRITERIA: List[Tuple[str, str, int, Tuple[str, ...], str]] = [
    ("fairness", "Équité de répartition des heures", 80, ("fairness",),
     "Répartit les heures selon ce que chacun peut réellement faire (jours où il peut travailler, ou objectif contractuel si renseigné) : la prochaine heure va à celui qui en a proportionnellement le moins. Le poids d'allocation n'intervient pas. Plus c'est haut, plus la répartition est égale."),
    ("time_pref", "Respect des préférences horaires", 60, ("time_pref", "preference"),
     "Pénalise les shifts hors de la préférence matin / middle / soir (non obligatoire) et des préférences d'horaires individuelles."),
    ("brand_priority", "Priorité d'affectation par marque", 90, ("secondary", "reinforce"),
     "Favorise les collaborateurs « prioritaires » sur une marque ; un collaborateur secondaire ou en renfort n'est utilisé qu'en dernier recours."),
    ("individual_priority", "Priorité individuelle des collaborateurs", 0, ("individual",),
     "Désactivée par défaut : aucune priorité automatique (ancienneté, mérite). Si vous l'activez, privilégie à couverture égale les collaborateurs au plus fort poids d'allocation (fiche collaborateur)."),
    ("hour_targets", "Respect des objectifs horaires", 85, ("budget", "budget_over", "overtime"),
     "Pénalise les heures de budget non planifiées, les dépassements de budget souple et les heures au-delà de l'objectif contractuel."),
    ("sunday_balance", "Équilibrage des dimanches", 75, ("sunday_balance",),
     "Répartit les dimanches entre les collaborateurs sans quota : réduit le nombre de dimanches du plus chargé."),
    ("alternation", "Alternance des shifts matin/soir", 40, ("alternation",),
     "Évite d'enchaîner un shift du matin puis du soir (ou l'inverse) deux jours de suite pour le même collaborateur."),
    ("family", "Relations entre collaborateurs", 90, ("family",),
     "Horaires opposés, binômes, collaborateurs à séparer, présence d'un tuteur : relations définies dans la fiche collaborateur et respectées lorsque c'est possible."),
    ("days_balance", "Équilibrage des jours travaillés", 65, ("days_balance",),
     "Répartit les jours de travail : réduit le nombre de jours du collaborateur le plus chargé."),
    ("cost", "Coût estimé", 50, ("cost",),
     "Privilégie les coûts horaires les plus bas, uniquement pour les contrats où le coût horaire est renseigné. Sans effet sinon."),
]
DEFAULT_UI: Dict[str, int] = {k: d for k, _l, d, _e, _x in CRITERIA}

# Poids bruts du moteur exposés en « avancé » (hors critères ci-dessus). La couverture des shifts obligatoires reste prioritaire par défaut.
ADVANCED: List[Tuple[str, str, str]] = [
    ("coverage", "Couverture des shifts obligatoires", "Pénalité par heure non couverte. Une valeur faible autorise davantage de shifts non couverts : à manier avec précaution."),
    ("sunday_quota", "Objectif exact de dimanches", "Pénalité par dimanche manquant lorsque le quota d'un collaborateur est en mode « objectif exact »."),
    ("stability", "Stabilité lors d'une réoptimisation", "Pénalité par affectation déplacée par rapport au planning existant."),
    ("balance", "Équilibre ouvertures / fermetures / week-ends", "Réduit le maximum individuel d'ouvertures, de fermetures et de week-ends."),
    ("fatigue", "Fatigue (5 jours consécutifs)", "Pénalité par série de cinq jours travaillés d'affilée."),
    ("rest_days", "Jours de repos hebdomadaires souhaités", "Pénalité par jour de repos souhaité non respecté."),
    ("site_change", "Changements de boutique", "Pénalité par changement de boutique d'un jour à l'autre."),
    ("stagger", "Prises de poste décalées", "Pénalité par prises de poste simultanées dans un groupe de coordination."),
]
ADVANCED_KEYS = [k for k, _l, _x in ADVANCED]
ADVANCED_MAX = 5000
_ENGINE_OF = {e: k for k, _l, _d, engs, _x in CRITERIA for e in engs}


ACTIVATION_BASE = {"individual": 1}  # critère désactivé par défaut : poids du moteur quand on l'active (+20 points = double)


def scale(default_engine: int, ui: int, default_ui: int, base: int = 0) -> int:
    if ui <= 0:
        return 0
    if default_engine == 0 and base:  # désactivé par défaut : 20 points = base, +20 points = double
        return max(0, round(base * 2 ** ((ui - 20) / 20)))
    return max(0, round(default_engine * 2 ** ((ui - default_ui) / 20)))


def engine_weights(criteria: Optional[Dict[str, int]] = None, advanced: Optional[Dict[str, int]] = None) -> Dict[str, int]:
    """Poids du moteur correspondant aux réglages ; toute clé absente garde sa valeur par défaut."""
    out = dict(DEFAULT_WEIGHTS)
    for key, _label, d, engs, _x in CRITERIA:
        ui = (criteria or {}).get(key, d)
        for e in engs:
            out[e] = scale(DEFAULT_WEIGHTS[e], int(ui), d, ACTIVATION_BASE.get(e, 0))
    for k, v in (advanced or {}).items():
        if k in ADVANCED_KEYS:
            out[k] = max(0, min(ADVANCED_MAX, int(v)))
    return out


def breakdown(objective: Dict[str, int]) -> Dict[str, int]:
    """Score (coût) par critère à partir de `SolverResult.objective` : sert à voir quels critères ont influencé le résultat."""
    out: Dict[str, int] = {}
    for term, val in objective.items():
        out[_ENGINE_OF.get(term, term)] = out.get(_ENGINE_OF.get(term, term), 0) + int(val)
    return out
