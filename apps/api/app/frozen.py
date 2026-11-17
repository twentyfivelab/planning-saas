"""Paramètres conservés par chaque planning.

Un planning garde les paramètres « habituels » (fiche collaborateur, disponibilités récurrentes, contrat, préférences, relations,
règles de l'entreprise) en vigueur au moment de sa création : un changement fait plus tard — par exemple pour préparer le mois
suivant — ne le modifie pas et n'y crée aucune incompatibilité. Les données propres au mois restent lues en direct : effectif du mois,
exceptions du mois, absences datées, collaborateur supprimé. Remplacer les paramètres d'un planning existant par les paramètres
actuels est toujours une action explicite (« Appliquer les paramètres actuels », ou une génération lancée avec ce choix)."""
from __future__ import annotations

from datetime import datetime, time, timezone
from typing import Any, Dict, List, Optional

from planning_solver.model import Contract, Employee as SEmployee, Relation, SolverConfig

VERSION = 1

# champs de la fiche conservés par le planning (tout le reste est propre au mois et lu en direct)
FICHE_FIELDS = ("brands", "skills", "weight", "contract", "legal_weekly_max_minutes", "available_weekdays", "unavailable_weekdays",
                "forbidden_tags", "max_days_per_week", "max_days_count", "max_days_period", "min_days_month", "max_days_month",
                "time_pref", "time_pref_strict", "latest_start", "preferred_times", "preferred_tags", "preference_strength",
                "weekly_rest_days_pref", "weekly_rest_days_hard", "rest_weekdays_hard", "rest_weekdays_soft", "allowed_sites",
                "preferred_sites", "opposite_of", "relations", "work_window")
# champs apparus après la création de plannings existants : absents d'un planning conservé = valeur par défaut du moteur (jamais la valeur
# actuelle, qui créerait un effet rétroactif) ; une différence est signalée et ne s'applique qu'avec « Appliquer les paramètres actuels »
LATE_FICHE = {"work_window": None}
LATE_CONFIG = {"travel_minutes": []}
RELATION_SCOPES = {"day": "même jour, tous sites", "overlap": "horaires qui se chevauchent"}
# règles de l'entreprise et pondérations UTILISÉES lors de la génération : les conditions de génération restent retrouvables
CONFIG_FIELDS = ("rest_hours", "max_consecutive_days", "weights", "hierarchical", "break_rules", "monthly_cap_minutes")
ROSTER_FIELDS = ("contract_ended",)  # effectif : collaborateur hors effectif parce que son contrat était terminé

LABELS = {
    "brands": "Marques autorisées", "skills": "Qualifications", "weight": "Poids d'attribution", "contract": "Contrat",
    "legal_weekly_max_minutes": "Durée hebdomadaire maximale du régime", "available_weekdays": "Jours de disponibilité",
    "unavailable_weekdays": "Indisponibilités hebdomadaires", "forbidden_tags": "Types de shift interdits",
    "max_days_per_week": "Jours maximum par semaine (règle)", "max_days_count": "Nombre maximum de jours", "max_days_period": "Période du maximum de jours",
    "min_days_month": "Minimum de jours par mois", "max_days_month": "Maximum de jours par mois", "time_pref": "Préférence horaire",
    "time_pref_strict": "Préférence horaire obligatoire", "latest_start": "Début au plus tard", "preferred_times": "Horaires préférés",
    "preferred_tags": "Types de shift préférés", "preference_strength": "Force des préférences", "weekly_rest_days_pref": "Jours de repos par semaine",
    "weekly_rest_days_hard": "Jours de repos obligatoires", "rest_weekdays_hard": "Jours de repos fixes (obligatoires)",
    "rest_weekdays_soft": "Jours de repos souhaités", "allowed_sites": "Sites autorisés", "preferred_sites": "Sites préférés",
    "opposite_of": "Horaires opposés avec", "relations": "Relations entre collaborateurs", "contract_ended": "Contrat terminé (hors effectif)",
    "rest_hours": "Repos quotidien minimum", "max_consecutive_days": "Jours consécutifs maximum", "weights": "Pondérations de l'algorithme",
    "hierarchical": "Optimisation hiérarchisée", "break_rules": "Pauses minimales", "monthly_cap_minutes": "Plafond mensuel d'heures",
    "work_window": "Horaires obligatoires", "travel_minutes": "Temps de déplacement entre sites",
}
DAYS = ("lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim.")
LEVELS = {"priority": "prioritaire", "secondary": "secondaire", "reinforce": "renfort"}


def _jsonable(v: Any) -> Any:
    if isinstance(v, (set, frozenset)):
        return sorted(_jsonable(x) for x in v)
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _jsonable(x) for k, x in sorted(v.items())}
    if isinstance(v, time):
        return v.isoformat()[:5]
    return v


def fiche_of(se: SEmployee) -> dict:
    out = {}
    for f in FICHE_FIELDS:
        v = getattr(se, f)
        if f == "contract":
            v = None if v is None else {k: getattr(v, k) for k in Contract.__dataclass_fields__}
        elif f == "relations":  # portée par défaut omise : les plannings conservés avant son apparition restent identiques
            v = sorted([r.kind, r.other, r.strict] + ([r.scope] if getattr(r, "scope", "site_day") != "site_day" else []) for r in v)
        out[f] = _jsonable(v)
    return out


def apply_fiche(se: SEmployee, d: dict) -> None:
    """Remet sur `se` les paramètres habituels conservés par le planning (types du moteur rétablis)."""
    for f in FICHE_FIELDS:
        if f not in d:
            if f in LATE_FICHE:
                setattr(se, f, LATE_FICHE[f])  # champ apparu après la conservation : valeur par défaut, jamais la valeur actuelle
            continue
        v = d[f]
        if f == "contract":
            v = None if v is None else Contract(**{k: v.get(k) for k in Contract.__dataclass_fields__})
        elif f == "relations":
            v = [Relation(r[0], r[1], bool(r[2]), r[3] if len(r) > 3 else "site_day") for r in v]
        elif f == "work_window":
            v = None if v is None else (time.fromisoformat(v[0]), time.fromisoformat(v[1]))
        elif f in ("skills", "unavailable_weekdays", "forbidden_tags", "preferred_tags", "rest_weekdays_hard", "rest_weekdays_soft", "preferred_sites"):
            v = set(v or [])
        elif f in ("available_weekdays", "allowed_sites"):
            v = None if v is None else set(v)
        elif f == "latest_start":
            v = None if v is None else time.fromisoformat(v)
        elif f == "preferred_times":
            v = {(time.fromisoformat(a), time.fromisoformat(b)) for a, b in (v or [])}
        elif f == "brands":
            v = dict(v or {})
        setattr(se, f, v)


def config_of(cfg: SolverConfig) -> dict:
    return {f: _jsonable(getattr(cfg, f)) for f in CONFIG_FIELDS}


def apply_config(cfg: SolverConfig, d: dict) -> None:
    for f in CONFIG_FIELDS:
        if f not in d:
            continue
        v = d[f]
        if f == "break_rules":
            v = [tuple(x) for x in v or []]
        elif f == "weights":
            v = {**cfg.weights, **(v or {})}
        setattr(cfg, f, v)


def snapshot(fiches: Dict[str, dict], cfg: dict, source: str) -> dict:
    return {"v": VERSION, "taken_at": datetime.now(timezone.utc).isoformat(), "source": source, "employees": fiches, "config": cfg}


def fmt(field: str, v: Any, names: Dict[str, str]) -> str:
    """Valeur lisible (comparaison des paramètres)."""
    if field == "travel_minutes" and not v:
        return "Aucun temps de déplacement"
    if v is None or v == [] or v == {}:
        return "Pas de préférence" if field not in ("contract", "skills", "brands") else "Non renseigné"
    if isinstance(v, bool):
        return "Oui" if v else "Non"
    if field == "brands":
        return ", ".join(f"{b} ({LEVELS.get(lv, lv)})" for b, lv in sorted(v.items()))
    if field in ("available_weekdays", "unavailable_weekdays", "rest_weekdays_hard", "rest_weekdays_soft"):
        return ", ".join(DAYS[int(x)] for x in v)
    if field in ("monthly_cap_minutes", "legal_weekly_max_minutes"):
        h, m = divmod(int(v), 60)
        return f"{h} h {m:02d}" if m else f"{h} h"
    if field == "rest_hours":
        return f"{v} h"
    if field == "opposite_of":
        return names.get(v, v)
    if field == "relations":
        kinds = {"avoid_together": "à séparer de", "work_together": "en binôme avec", "mentor": "tuteur :"}
        return "; ".join(f"{kinds.get(r[0], r[0])} {names.get(r[1], r[1])}{' (' + RELATION_SCOPES[r[3]] + ')' if len(r) > 3 and r[3] in RELATION_SCOPES else ''}"
                         f"{' (strict)' if r[2] else ''}" for r in v)
    if field == "work_window":
        return f"{v[0]}–{v[1]}"
    if field == "travel_minutes":
        return "; ".join(f"{a} ↔ {b} : {mi} min" for a, b, mi in v)
    if field == "contract":
        parts = []
        for k, lab in (("monthly_target_minutes", "objectif"), ("monthly_min_minutes", "minimum"), ("monthly_max_minutes", "maximum"),
                       ("weekly_max_minutes", "max. hebdo")):
            if v.get(k) is not None:
                parts.append(f"{lab} {fmt('monthly_cap_minutes', v[k], names)}")
        if v.get("activity_rate") is not None:
            parts.append(f"taux {round(v['activity_rate'] * 100)} %")
        return ", ".join(parts) or "Non renseigné"
    if field == "weights":
        return f"{len(v)} pondérations"
    if isinstance(v, list):
        return ", ".join(str(x if not isinstance(x, list) else "–".join(map(str, x))) for x in v)
    return str(v)


def differences(frozen: Optional[dict], fiches: Dict[str, dict], cfg: dict, names: Dict[str, str]) -> List[dict]:
    """Paramètres actuels qui diffèrent de ceux conservés par le planning : [{employee, field, label, planning, current}]."""
    if not frozen:
        return []
    out: List[dict] = []
    old_cfg = frozen.get("config", {})
    for f in CONFIG_FIELDS:
        if f in old_cfg and old_cfg.get(f) != cfg.get(f):
            if f == "weights":
                changed = sorted(k for k in set(old_cfg[f] or {}) | set(cfg[f] or {}) if (old_cfg[f] or {}).get(k) != (cfg[f] or {}).get(k))
                out.append({"employee": None, "field": f, "label": LABELS[f], "planning": f"{len(changed)} pondération(s) différente(s)",
                            "current": ", ".join(changed)})
                continue
            out.append({"employee": None, "field": f, "label": LABELS[f], "planning": fmt(f, old_cfg.get(f), names), "current": fmt(f, cfg.get(f), names)})
    for f, default in LATE_CONFIG.items():
        before = old_cfg.get(f, default)
        if f in cfg and before != cfg[f]:
            out.append({"employee": None, "field": f, "label": LABELS[f], "planning": fmt(f, before, names), "current": fmt(f, cfg[f], names)})
    old = frozen.get("employees", {})
    for code, cur in sorted(fiches.items(), key=lambda kv: names.get(kv[0], kv[0])):
        prev = old.get(code)
        if prev is None:
            out.append({"employee": names.get(code, code), "employee_id": code, "field": "new", "label": "Collaborateur ajouté après la création du planning",
                        "planning": "—", "current": "présent"})
            continue
        for f in FICHE_FIELDS + ROSTER_FIELDS:
            if f not in prev and f in LATE_FICHE:
                prev = {**prev, f: LATE_FICHE[f]}
            if f in prev and prev.get(f) != cur.get(f):
                out.append({"employee": names.get(code, code), "employee_id": code, "field": f, "label": LABELS[f],
                            "planning": fmt(f, prev.get(f), names), "current": fmt(f, cur.get(f), names)})
    return out
