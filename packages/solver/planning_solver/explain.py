"""« Pourquoi ce collaborateur sur ce shift ? » Uniquement des faits vérifiables : les règles strictes contrôlées (avec leurs valeurs),
les critères observés et leur contribution chiffrée au coût du planning, et la comparaison avec les autres candidats compatibles.
Un solveur optimise l'ensemble du planning : aucune cause unique n'est inventée, le texte le dit explicitement."""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from typing import Dict, List, Optional

from .context import Prepared, prepare, preference_checks
from .model import CATEGORY_LABEL, Assignment, SolverInput
from .objective import Evaluator
from .replace import LEVEL_LABEL, rank_replacements, term_lines
from .timecalc import shift_bounds

CAVEAT = ("Le moteur optimise le planning dans son ensemble : ces éléments sont les critères observés pour cette affectation, "
          "pas une cause unique démontrée.")


def _check(ok: bool, code: str, label: str, detail: str) -> dict:
    return {"ok": bool(ok), "code": code, "label": label, "detail": detail}


def explain_assignment(inp: SolverInput, assignments: List[Assignment], slot_id: str, prep: Optional[Prepared] = None) -> Dict[str, object]:
    prep = prep or prepare(inp)
    s = prep.slots[slot_id]
    a = next(x for x in assignments if x.slot_id == slot_id)
    e = prep.emps[a.employee_id]
    mine = sorted((x for x in assignments if x.employee_id == e.id), key=lambda x: prep.slots[x.slot_id].bounds[0])
    cfg = inp.config
    checks: List[dict] = []
    levels = {b: e.brands.get(b) for b in s.brands}
    unauthorized = [b for b, lv in levels.items() if lv is None]
    checks.append(_check(not unauthorized, "BRAND", "Marque autorisée dans la fiche",
                         ", ".join(f"{b} : {LEVEL_LABEL.get(lv, 'non autorisée')}" for b, lv in levels.items())))
    if s.required_skills:
        lacking = [k for k in s.required_skills if k not in e.skills]
        checks.append(_check(not lacking, "SKILLS", "Qualifications requises", "Possède : " + ", ".join(s.required_skills) if not lacking else "Manque : " + ", ".join(lacking)))
    blocked = e.blocked(s.day) or s.day.weekday() in e.rest_weekdays_hard
    checks.append(_check(not blocked, "AVAILABLE", "Disponible à cette date", "Aucune indisponibilité enregistrée ce jour-là" if not blocked else "Indisponibilité enregistrée ce jour-là"))
    if e.allowed_sites is not None:
        checks.append(_check(s.site in e.allowed_sites, "SITE", "Site autorisé", ", ".join(sorted(e.allowed_sites))))
    # repos avant et après, y compris avec les périodes voisines
    b0, b1 = s.bounds
    others = [prep.slots[x.slot_id].bounds for x in mine if x.slot_id != slot_id]
    others += [shift_bounds(o.day, o.start, o.end) for o in inp.outside_shifts if o.employee_id == e.id]
    gaps = [(b0 - o1).total_seconds() / 3600 for _o0, o1 in others if o1 <= b0] + [(o0 - b1).total_seconds() / 3600 for o0, _o1 in others if o0 >= b1]
    overlap = any(o0 < b1 and b0 < o1 for o0, o1 in others)
    gap = min(gaps) if gaps else None
    checks.append(_check(not overlap and (gap is None or gap >= cfg.rest_hours), "REST", f"Repos d'au moins {cfg.rest_hours} h",
                         "Chevauchement avec un autre shift" if overlap else "Aucun autre shift proche" if gap is None else f"Plus court repos autour de ce shift : {gap:g} h"))
    # jours consécutifs et jours de la semaine
    days = {x.day for x in mine} | {o.day for o in inp.outside_shifts if o.employee_id == e.id}
    run, d = 1, s.day - timedelta(days=1)
    while d in days:
        run, d = run + 1, d - timedelta(days=1)
    d = s.day + timedelta(days=1)
    while d in days:
        run, d = run + 1, d + timedelta(days=1)
    checks.append(_check(run <= cfg.max_consecutive_days, "CONSECUTIVE", f"Au plus {cfg.max_consecutive_days} jours consécutifs", f"Série en cours : {run} jour{'s' if run > 1 else ''}"))
    cap = e.max_days_per_week
    if e.max_days_count is not None and e.max_days_period == "week":
        cap = e.max_days_count if cap is None else min(cap, e.max_days_count)
    if cap is not None:
        n = sum(1 for d in days if d.isocalendar()[:2] == s.day.isocalendar()[:2])
        checks.append(_check(n <= cap, "MAX_DAYS_WEEK", "Limite de jours par semaine", f"{n} jour(s) cette semaine pour un maximum de {cap}"))
    if e.max_days_count is not None and e.max_days_period == "month":
        n = len({x.day for x in mine})
        checks.append(_check(n <= e.max_days_count, "MAX_DAYS_MONTH", "Limite de jours sur la période", f"{n} jour(s) pour un maximum de {e.max_days_count}"))
    if s.day.weekday() == 6 and e.sunday_quota is not None:
        n = sum(1 for x in mine if x.day.weekday() == 6)
        checks.append(_check(n <= e.sunday_quota, "SUNDAY_QUOTA", "Quota de dimanches du mois", f"{n} dimanche(s) planifié(s) pour un quota de {e.sunday_quota}"))
    minutes = sum(x.effective_minutes for x in mine)
    c = e.contract
    if c and c.weekly_max_minutes is not None:
        n = sum(x.effective_minutes for x in mine if x.day.isocalendar()[:2] == s.day.isocalendar()[:2])
        checks.append(_check(n <= c.weekly_max_minutes, "CONTRACT_WEEKLY_MAX", "Maximum hebdomadaire du contrat", f"{n / 60:g} h cette semaine pour {c.weekly_max_minutes / 60:g} h"))
    if c and c.monthly_max_minutes is not None and not c.overtime_allowed:
        checks.append(_check(minutes <= c.monthly_max_minutes, "CONTRACT_MONTHLY_MAX", "Maximum mensuel du contrat", f"{minutes / 60:g} h pour {c.monthly_max_minutes / 60:g} h"))

    # critères observés
    observed: List[dict] = []
    target = c.monthly_target_minutes if c and c.monthly_target_minutes else prep.targets.get(e.id, 0)
    kind = "objectif contractuel" if c and c.monthly_target_minutes else "part équitable calculée"
    observed.append({"label": "Objectif horaire", "tone": "favorable" if minutes <= target else "defavorable",
                     "detail": f"{minutes / 60:g} h planifiées dont ce shift ; {kind} : {target / 60:g} h"})
    for b, lv in levels.items():
        if lv:
            observed.append({"label": f"Niveau sur {b}", "tone": "favorable" if lv == "priority" else "defavorable" if lv == "reinforce" else "neutre", "detail": LEVEL_LABEL[lv]})
    cat = prep.category[slot_id]
    if e.time_pref:
        if cat is None:
            observed.append({"label": "Préférence horaire", "tone": "neutre", "detail": f"Préférence {CATEGORY_LABEL[e.time_pref].lower()} ; un seul horaire sur ce site : critère sans objet"})
        else:
            observed.append({"label": "Préférence horaire", "tone": "favorable" if cat == e.time_pref else "defavorable",
                             "detail": f"Préférence {CATEGORY_LABEL[e.time_pref].lower()} ; ce shift : {CATEGORY_LABEL[cat].lower()}{' (obligatoire)' if e.time_pref_strict else ''}"})
    else:
        observed.append({"label": "Préférence horaire", "tone": "neutre", "detail": "Pas de préférence dans la fiche"})
    for code, ok, _f in preference_checks(e, s):
        label = {"repos_souhaite": "Jour de repos souhaité", "site_prefere": "Site préféré", "horaire_prefere": "Horaire préféré"}.get(code, "Préférence individuelle")
        observed.append({"label": label, "tone": "favorable" if ok else "defavorable", "detail": "Respecté" if ok else "Non respecté"})
    if slot_id in inp.locked:
        observed.append({"label": "Verrouillage", "tone": "neutre", "detail": "Affectation verrouillée : le moteur l'a conservée telle quelle"})
    if inp.previous.get(slot_id) == e.id:
        observed.append({"label": "Stabilité", "tone": "favorable", "detail": "Déjà affecté·e à ce shift avant la dernière réoptimisation"})

    # contribution chiffrée : coût de ce planning comparé au même planning avec ce shift à un autre candidat
    ranking = rank_replacements(inp, assignments, slot_id, prep)
    alternatives = [{"name": r["name"], "extra_cost": r["delta_cost"], "terms": r["terms"][:4]} for r in ranking["candidates"] if r["status"] == "compatible"][:5]
    ev = Evaluator(inp, assignments, prep)
    removal: Dict[str, int] = defaultdict(int)
    for k, v in ev.delta(slot_id, None).items():
        removal[k] = v
    return {"employee": e.name, "employee_id": e.id, "slot_id": slot_id, "day": s.day.isoformat(), "site": s.site, "start": s.start.isoformat()[:5], "end": s.end.isoformat()[:5],
            "brands": list(s.brands), "checks": checks, "all_rules_ok": all(x["ok"] for x in checks), "observed": observed,
            "effect_of_removing": term_lines(dict(removal)), "alternatives": alternatives, "better_alternatives": sum(1 for x in alternatives if x["extra_cost"] < 0),
            "compatible_candidates": ranking["compatible"], "weights": ev.W, "caveat": CAVEAT}
