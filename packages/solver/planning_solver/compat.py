"""Compatibilité d'un planning existant avec un jeu de paramètres (ceux du planning ou les paramètres actuels), sans rien modifier.

Chaque incompatibilité est détaillée : collaborateur, shifts concernés (date, horaires, site), règle, raison précise, et sa nature :
« obligatoire » (contrainte dure non respectée) ou « préférence » (souhait ou objectif non atteint, jamais bloquant)."""
from __future__ import annotations

from typing import Dict, List, Optional

from .model import Assignment, CATEGORY_LABEL, SolverInput, site_start_times, slot_category
from .validator import Violation, violations

RULE_LABELS: Dict[str, str] = {
    "UNAVAILABLE": "Disponibilité du collaborateur",
    "EXCLUDED_FROM_PERIOD": "Effectif du mois",
    "EMPLOYEE_REMOVED": "Collaborateur supprimé",
    "BRAND_NOT_ELIGIBLE": "Marques autorisées",
    "SITE_NOT_ALLOWED": "Sites autorisés",
    "SKILL_MISSING": "Qualification requise",
    "FORBIDDEN_TAG": "Type de shift interdit",
    "REST_WEEKDAY": "Jour de repos obligatoire",
    "TIME_PREF_STRICT": "Préférence horaire obligatoire",
    "MAX_DAYS_WEEK": "Nombre maximum de jours par semaine",
    "MAX_DAYS_MONTH": "Nombre maximum de jours par mois",
    "MONTHLY_CAP": "Plafond mensuel d'heures (règle de l'entreprise)",
    "SUNDAY_QUOTA": "Quota de dimanches",
    "REST": "Repos quotidien minimum",
    "CONSECUTIVE": "Jours consécutifs maximum",
    "CONTRACT_WEEKLY_MAX": "Maximum hebdomadaire du contrat",
    "CONTRACT_MONTHLY_MAX": "Maximum mensuel du contrat",
    "LEGAL_WEEKLY_MAX": "Durée hebdomadaire maximale du régime applicable",
    "REST_DAYS_HARD": "Jours de repos hebdomadaires obligatoires",
    "BUDGET_EXCEEDED": "Budget horaire strict de la marque",
    "SCHEDULE_NOT_ALLOWED": "Horaires autorisés de la boutique",
    "BREAK_TOO_SHORT": "Pause minimale",
    "RELATION_AVOID": "Collaborateurs à ne pas réunir",
    "MENTOR_MISSING": "Présence d'un tuteur",
    "DAY_GROUP": "Un seul shift par groupe de jours",
    "DOUBLE_ASSIGNMENT": "Un seul titulaire par shift",
    "LOCK_VIOLATED": "Affectation verrouillée",
    "OVERLAP": "Chevauchement de shifts",
    "HOURS_MISMATCH": "Durées du shift",
    "ALLOCATION_MISMATCH": "Imputation aux marques",
    "FROZEN_SLOT": "Périmètre de la réoptimisation",
    "TIME_PREF": "Préférence horaire (souple)",
    "MIN_DAYS_NOT_MET": "Nombre minimum de jours par mois",
}


def _cat(v: Optional[str]) -> str:
    return CATEGORY_LABEL.get(v or "", v or "—").lower()


def _reason(v: Violation, name: str) -> str:
    c, lim, got = v.code, v.limit, v.reached
    if c == "UNAVAILABLE":
        return f"{name} est indisponible ce jour-là (indisponibilité, congé ou jour hors de ses disponibilités)."
    if c == "EXCLUDED_FROM_PERIOD":
        return f"{name} est exclu·e de l'effectif de ce mois."
    if c == "EMPLOYEE_REMOVED":
        return f"{name} a été supprimé·e de l'équipe ({lim}) : ce shift doit être réattribué."
    if c == "BRAND_NOT_ELIGIBLE":
        return f"Marque {got} non autorisée pour {name} (marques autorisées : {lim})."
    if c == "SITE_NOT_ALLOWED":
        return f"Site {got} hors des sites autorisés de {name} ({lim})."
    if c == "SKILL_MISSING":
        return f"Qualification manquante : {got}."
    if c == "FORBIDDEN_TAG":
        return f"Type de shift « {got} » interdit pour {name}."
    if c == "REST_WEEKDAY":
        return f"Ce jour est un jour de repos obligatoire de {name}."
    if c == "TIME_PREF_STRICT":
        return f"Shift « {_cat(got)} » alors que la préférence « {_cat(lim)} » de {name} est obligatoire."
    if c == "MAX_DAYS_WEEK":
        return f"{got} travaillés dans la semaine pour un maximum de {lim}."
    if c == "MAX_DAYS_MONTH":
        return f"{got} travaillés dans le mois pour un maximum de {lim} (une journée compte une seule fois)."
    if c == "MIN_DAYS_NOT_MET":
        return f"{got} travaillés dans le mois pour un minimum de {lim} (une journée compte une seule fois)."
    if c == "MONTHLY_CAP":
        return f"{got} de travail effectif dans le mois, tous sites et marques cumulés, pour un plafond de {lim}."
    if c == "SUNDAY_QUOTA":
        return f"{got} travaillé(s) pour un maximum de {lim}."
    if c == "REST":
        return f"Repos de {got} entre deux shifts pour un minimum de {lim}." if got else f"Repos inférieur à {lim} avec un shift d'une période voisine."
    if c == "CONSECUTIVE":
        return f"{got} consécutifs travaillés pour un maximum de {lim}."
    if c in ("CONTRACT_WEEKLY_MAX", "LEGAL_WEEKLY_MAX"):
        return f"{got} de travail effectif dans la semaine pour un maximum de {lim}."
    if c == "CONTRACT_MONTHLY_MAX":
        return f"{got} de travail effectif dans le mois pour un maximum contractuel de {lim}."
    if c == "REST_DAYS_HARD":
        return f"{got} travaillés dans la semaine pour {lim} au plus (jours de repos obligatoires)."
    if c == "BUDGET_EXCEEDED":
        return f"{got} planifiées pour un budget strict de {lim}."
    if c == "SCHEDULE_NOT_ALLOWED":
        return f"Horaire {got} hors des horaires autorisés de la boutique."
    if c == "BREAK_TOO_SHORT":
        return f"Pause de {got} pour {lim} exigées par le référentiel."
    detail = v.text.split(": ", 1)[1] if ": " in v.text else v.text
    return detail[0].upper() + detail[1:] + ("" if detail.endswith(".") else ".")


def compatibility(inp: SolverInput, assignments: List[Assignment]) -> Dict[str, object]:
    """hard = violations de contraintes dures (textes historiques) ; soft = préférences non respectées ; items = détail structuré
    de chaque incompatibilité (obligatoire ou préférence). Lecture seule."""
    found = violations(inp, assignments)
    slots = {s.id: s for s in inp.slots}
    emps = {e.id: e for e in inp.employees}

    def shifts(ids: List[str]) -> List[dict]:
        out = []
        for sid in ids:
            s = slots.get(sid)
            if s is not None:
                out.append({"slot_id": sid, "day": s.day.isoformat(), "start": s.start.isoformat()[:5], "end": s.end.isoformat()[:5], "site": s.site,
                            "brands": sorted(s.brands)})
        return sorted(out, key=lambda x: (x["day"], x["start"]))

    items: List[dict] = []
    for v in found:
        e = emps.get(v.employee or "")
        name = e.name if e else "—"
        if v.code == "BUDGET_EXCEEDED":
            name = "—"
        items.append({"kind": "obligatoire", "code": v.code, "rule": RULE_LABELS.get(v.code, v.code), "employee_id": v.employee, "employee": name,
                      "shifts": shifts(v.slots), "days": [d.isoformat() for d in v.days], "reason": _reason(v, name),
                      "limit": v.limit, "reached": v.reached, "text": v.text})
    starts = site_start_times(inp)
    soft: List[dict] = []
    for a in assignments:
        e, s = emps.get(a.employee_id), slots.get(a.slot_id)
        if e is None or s is None or not e.time_pref or e.time_pref_strict:
            continue
        cat = slot_category(s, starts)
        if cat is not None and cat != e.time_pref:
            text = f"{e.name} : préférence « {CATEGORY_LABEL[e.time_pref]} » non respectée sur {a.slot_id} ({CATEGORY_LABEL[cat].lower()})."
            soft.append({"slot_id": a.slot_id, "employee": e.name, "kind": "time_pref", "text": text})
            items.append({"kind": "preference", "code": "TIME_PREF", "rule": RULE_LABELS["TIME_PREF"], "employee_id": e.id, "employee": e.name,
                          "shifts": shifts([a.slot_id]), "days": [], "limit": CATEGORY_LABEL[e.time_pref], "reached": CATEGORY_LABEL[cat],
                          "reason": f"Shift « {CATEGORY_LABEL[cat].lower()} » alors que {e.name} préfère « {CATEGORY_LABEL[e.time_pref].lower()} » "
                                    "(préférence souple : l'affectation reste permise).", "text": text})
    return {"hard": [v.text for v in found], "soft": soft, "items": items, "checked": len(assignments)}
