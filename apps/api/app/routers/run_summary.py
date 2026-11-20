"""Résultat d'une génération en six blocs distincts, compréhensibles sans connaître le moteur :
règles obligatoires · couverture des besoins · budgets et volume · équité des heures · shifts à compléter · état de l'optimisation.
« Valide », « couverture complète » et « optimum prouvé » sont trois informations différentes. Lecture seule."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from .. import models as m
from ..deps import Ctx, get_or_404, require

router = APIRouter(tags=["résultat d'une génération"])

PRIORITIES = [
    "Règles obligatoires, jamais sacrifiées : disponibilités et indisponibilités, marques autorisées, repos, jours consécutifs, jours maximum, "
    "plafond mensuel, budgets stricts, affectations verrouillées. Le résultat est revérifié par un contrôle indépendant avant et après l'enregistrement.",
    "Couverture des besoins obligatoires, puis des budgets du mois (volume visé pour les besoins optionnels).",
    "Engagements : objectifs contractuels, quotas de dimanches, budgets souples.",
    "Optimisation : équité des heures — une cible commune d'heures pour toute l'équipe, plafonnée par ce que chacun peut réellement faire "
    "(jours possibles, jours maximum, plafond, shifts partagés avec des collègues) et remplacée par l'objectif contractuel explicite le cas échéant ; préférences horaires, "
    "niveau sur la marque (prioritaire, puis secondaire, le renfort en dernier recours), équilibre des dimanches et des jours, stabilité.",
    "Jamais d'avantage automatique selon l'ancienneté ou le mérite : ces ajustements restent manuels.",
]


def _h(minutes) -> str:
    h, mi = divmod(int(minutes or 0), 60)
    return f"{h} h {mi:02d}" if mi else f"{h} h"


@router.get("/runs/{rid}/summary")
def run_summary(rid: str, ctx: Ctx = Depends(require("planning.read"))):
    run = get_or_404(ctx, m.OptimizationRun, rid)
    p = ctx.db.get(m.PlanningPeriod, run.period_id)
    if p is None or p.deleted_at is not None:
        raise HTTPException(404, "Introuvable")
    res = ctx.db.scalar(select(m.OptimizationResult).where(m.OptimizationResult.run_id == run.id))
    rep = (res.report or {}) if res else {}
    save = rep.get("save") or {}
    met = rep.get("metrics") or {}
    ver = rep.get("verification") or {}
    limit = (run.config or {}).get("time_limit_s")
    saved = save.get("outcome") == "replaced"

    # 1) règles obligatoires (contrôle indépendant)
    viol = list(((ver.get("after_save") or {}).get("violations")) or ((ver.get("solver_result") or {}).get("violations")) or rep.get("hard_violations") or [])
    checked = (ver.get("after_save") or ver.get("solver_result") or {}).get("checked", 0)
    if not ver.get("executed"):
        rules = {"state": "info", "text": "Aucun planning à contrôler pour ce calcul."}
    elif viol:
        rules = {"state": "bad", "text": f"{len(viol)} règle(s) obligatoire(s) non respectée(s) : le planning n'a pas été enregistré."}
    else:
        rules = {"state": "ok", "text": f"Toutes les règles obligatoires sont respectées : {checked} affectation(s) revérifiée(s) par un contrôle indépendant."}
    rules.update(title="Règles obligatoires", checked=checked, violations=viol[:20])

    # 2) couverture des besoins obligatoires
    mand, cov = int(met.get("mandatory_shifts") or 0), int(met.get("covered_shifts") or 0)
    unc, unc_min = int(met.get("uncovered_shifts") or 0), int(met.get("uncovered_minutes") or 0)
    if not mand:
        coverage = {"state": "info", "text": "Aucun besoin obligatoire ce mois-ci."}
    elif unc:
        coverage = {"state": "warn", "text": f"{cov} shift(s) obligatoire(s) couvert(s) sur {mand} ; {unc} non couvert(s) ({_h(unc_min)}) : aucun collaborateur ne peut les prendre sans enfreindre une règle obligatoire.",
                    "action": {"label": "Voir les shifts non couverts", "href": "/planning"}}
    else:
        coverage = {"state": "ok", "text": f"Couverture complète : les {mand} shift(s) obligatoire(s) sont attribués."}
    coverage.update(title="Couverture des besoins", mandatory=mand, covered=cov, uncovered=unc, uncovered_minutes=unc_min)

    # 3) budgets et volume attribué
    brands = []
    for b in rep.get("budgets") or []:
        if b.get("target_minutes") is None:
            continue
        over = (b.get("planned_minutes") or 0) > b["target_minutes"]
        brands.append({"brand": b.get("brand"), "target_minutes": b["target_minutes"], "planned_minutes": b.get("planned_minutes") or 0,
                       "strict": bool(b.get("strict", True)), "state": "warn" if over else "ok"})
    vol = save.get("volume")
    if vol and vol.get("note"):
        budgets = {"state": "warn", "text": vol["note"]}
    elif not brands:
        budgets = {"state": "info", "text": "Aucun budget saisi pour ce mois : le volume des besoins optionnels n'est pas visé."
                   + (f" Volume attribué : {vol['after']['mandatory']} shift(s) obligatoire(s), {vol['after']['optional']} optionnel(s), {_h(vol['after']['minutes'])}." if vol else "")}
    else:
        budgets = {"state": "warn" if any(x["state"] == "warn" for x in brands) else "ok",
                   "text": f"{len(brands)} budget(s) suivi(s)." + (f" Volume attribué : {vol['after']['mandatory']} obligatoire(s), {vol['after']['optional']} optionnel(s), {_h(vol['after']['minutes'])}." if vol else "")}
    budgets.update(title="Budgets et volume attribué", brands=brands, volume=vol)

    # 4) équité des heures (cible commune plafonnée par ce que chacun peut réellement atteindre, compte tenu des autres)
    fair = rep.get("fairness") or {}
    emps, ratios, limited = [], [], 0
    for _code, f in fair.items():
        ref, cap, mi, tgt = f.get("ref") or 0, f.get("cap") or 0, f.get("minutes") or 0, f.get("target") or 0
        flag = None
        if not f.get("eligible"):
            flag = "aucun shift possible ce mois (marques sans besoin)"
        elif ref == 0:
            flag = "en renfort uniquement sur les marques qui ont des besoins (dernier recours)"
        elif cap and mi >= cap - 480:
            flag, limited = "au maximum de ce qu'il peut faire", limited + 1
        elif tgt - mi > 16 * 60:
            flag = "en dessous de sa part équitable"
        elif not f.get("explicit") and ref and tgt < ref - 60:
            flag = "part réduite : partage les mêmes shifts avec d'autres collaborateurs, la cible commune n'est pas atteignable pour lui"
        ratio = round(mi / ref, 2) if ref else None
        if ratio is not None and f.get("eligible"):
            ratios.append(ratio)
        emps.append({"name": f.get("name"), "minutes": mi, "target_minutes": tgt, "capacity_minutes": cap, "ratio": ratio, "flag": flag})
    emps.sort(key=lambda e: (e["ratio"] if e["ratio"] is not None else 9, e["name"] or ""))
    if not saved or not ratios:
        fairness = {"state": "info", "text": "Équité non évaluée (aucun planning enregistré par ce calcul)." if not saved else "Aucun collaborateur à comparer."}
        spread = None
    else:
        spread = {"min": min(ratios), "max": max(ratios)}
        below = sum(1 for e in emps if e["flag"] == "en dessous de sa part équitable")
        common = max((f.get("ref") or 0) for f in fair.values()) if fair else 0
        fairness = {"state": "ok" if spread["max"] - spread["min"] <= 0.25 and not below else "warn",
                    "text": f"Cible commune : {_h(common)} par collaborateur, plafonnée par ce que chacun peut réellement faire, y compris en tenant compte "
                            f"des collègues qui se partagent les mêmes shifts (objectif contractuel le cas échéant). "
                            f"Heures attribuées : entre {round(spread['min'] * 100)} % et {round(spread['max'] * 100)} % de la cible."
                    + (f" {limited} collaborateur(s) au maximum de ce qu'ils peuvent faire." if limited else "")
                    + (f" {below} collaborateur(s) nettement en dessous de leur part : voir le détail." if below else "")}
    fairness.update(title="Équité des heures", employees=emps, spread=spread)

    # 5) shifts restant à compléter (état actuel du planning)
    from .optional_needs import optional_needs
    opt = optional_needs(str(p.id), ctx) if saved else {"total": 0, "minutes": 0}
    remaining = {"state": "ok" if not unc and not opt["total"] else ("warn" if unc else "info"),
                 "text": (f"{unc} shift(s) obligatoire(s) non couvert(s). " if unc else "Aucun shift obligatoire à compléter. ")
                 + (f"{opt['total']} besoin(s) optionnel(s) non attribué(s) ({_h(opt['minutes'])}), à compléter à la main si vous le souhaitez." if opt["total"] else ""),
                 "action": {"label": "Voir les besoins à compléter", "href": "/planning#besoins-optionnels"} if opt["total"] or unc else None,
                 "title": "Shifts à compléter", "mandatory_uncovered": unc, "optional_unassigned": opt["total"], "optional_minutes": opt["minutes"]}

    # 6) état de l'optimisation
    levels = [{"level": lv.get("level"), "proved": bool(lv.get("proved_optimal")), "seconds": lv.get("seconds")} for lv in rep.get("levels") or []]
    if run.status == "annule":
        optim = {"state": "info", "text": "Calcul annulé : le planning existant n'a pas été modifié."}
    elif not saved:
        optim = {"state": "warn", "text": save.get("reason") or "Aucun planning enregistré par ce calcul."}
    elif rep.get("proved_optimal"):
        optim = {"state": "ok", "text": "Meilleure solution prouvée pour les critères choisis."}
    else:
        optim = {"state": "info", "text": f"Planning valide et utilisable, mais optimisation non terminée : la durée maximale{f' ({limit} s)' if limit else ''} a été atteinte avant de prouver la meilleure répartition. Une durée plus longue peut encore l'améliorer."}
    optim.update(title="État de l'optimisation", proved=bool(rep.get("proved_optimal")), levels=levels)

    return {"run": {"id": str(run.id), "status": run.status, "period": p.name, "month": p.start_date.strftime("%Y-%m"), "time_limit_s": limit, "saved": saved,
                    "save_reason": save.get("reason")},
            "blocks": {"rules": rules, "coverage": coverage, "budgets": budgets, "fairness": fairness, "remaining": remaining, "optimisation": optim},
            "priorities": PRIORITIES}
