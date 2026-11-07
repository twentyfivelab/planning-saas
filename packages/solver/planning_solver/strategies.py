"""Stratégies de simulation : mêmes contraintes dures, même hiérarchie (couverture d'abord) ; seule l'importance relative des critères
change. Les multiplicateurs s'appliquent aux poids réglés par l'entreprise, jamais à une valeur figée."""
from typing import Dict, List, TypedDict


class Strategy(TypedDict):
    key: str
    label: str
    description: str
    multipliers: Dict[str, int]
    keep_current: bool  # part du planning existant : chaque changement est pénalisé


STRATEGIES: List[Strategy] = [
    {"key": "couverture", "label": "Couverture maximale", "description": "Réglages actuels de l'entreprise : couvrir d'abord tous les postes, puis optimiser le reste.",
     "multipliers": {}, "keep_current": False},
    {"key": "equite", "label": "Équité prioritaire", "description": "Rapproche chacun de son objectif horaire ; répartit dimanches, jours, ouvertures et fermetures.",
     "multipliers": {"fairness": 4, "balance": 3, "sunday_balance": 3, "days_balance": 3, "alternation": 2}, "keep_current": False},
    {"key": "preferences", "label": "Préférences des collaborateurs", "description": "Renforce les préférences horaires, jours de repos, sites souhaités et relations.",
     "multipliers": {"time_pref": 4, "preference": 4, "family": 3, "rest_days": 3}, "keep_current": False},
    {"key": "marques", "label": "Priorités de marques renforcées", "description": "Utilise d'abord les collaborateurs prioritaires ; les renforts en dernier recours.",
     "multipliers": {"reinforce": 4, "secondary": 4, "individual": 3}, "keep_current": False},
    {"key": "cout", "label": "Coût minimal", "description": "Privilégie les coûts horaires les plus bas. Sans effet tant qu'aucun coût horaire n'est renseigné dans les contrats.",
     "multipliers": {"cost": 20}, "keep_current": False},
    {"key": "stabilite", "label": "Stabilité maximale", "description": "Part du planning existant et ne le modifie que si c'est nécessaire.",
     "multipliers": {"stability": 8}, "keep_current": True},
]
BY_KEY = {s["key"]: s for s in STRATEGIES}


def apply_strategy(weights: Dict[str, int], key: str) -> Dict[str, int]:
    out = dict(weights)
    for term, factor in BY_KEY[key]["multipliers"].items():
        out[term] = out.get(term, 0) * factor
    return out
