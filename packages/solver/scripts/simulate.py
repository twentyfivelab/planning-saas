"""Génère docs/simulation-2026-11.md : python scripts/simulate.py [sortie.md]"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from planning_solver import solve  # noqa: E402
from planning_solver.demo_nov2026 import build_input, TOTAL_HOURS  # noqa: E402
from planning_solver.model import SolverConfig  # noqa: E402

inp = build_input(config=SolverConfig(time_limit_s=60))
r = solve(inp)
names = {e.id: e.name for e in inp.employees}
L = ["# Rapport de simulation — novembre 2026 (généré)", "",
     "> **Simulation exploratoire, non validable** : aucun contrat, aucune disponibilité complète ni congé fournis. "
     "Outil d'aide à la décision, pas un conseil juridique ; validation par un spécialiste du droit suisse requise.",
     "", f"- Statut : **{r.status}** — mode : **{r.mode}** — validable : **{r.validable}**",
     f"- Durée de calcul : {r.duration_s} s — violations dures détectées par le vérificateur : {len(r.hard_violations)}",
     f"- Budget total déclaré : {TOTAL_HOURS} h ; planifié : {sum(a.effective_minutes for a in r.assignments) / 60:g} h",
     "", "## Budgets (heures effectives)", "", "| Marque | Budget | Planifié | Restant | Besoins définis |",
     "|---|---:|---:|---:|---|"]
for b in r.budgets:
    L.append(f"| {b['brand']} | {b['target_minutes'] / 60:g} | {b['planned_minutes'] / 60:g} | "
             f"{b['remaining_minutes'] / 60:g} | {'oui' if b['requirements_defined'] else '**non — à renseigner**'} |")
L += ["", "## Heures par collaborateur", "", "| Collaborateur | Heures effectives |", "|---|---:|"]
L += [f"| {names[k]} | {v / 60:g} |" for k, v in sorted(r.employee_hours.items(), key=lambda kv: -kv[1])]
L += ["", "## Données manquantes et hypothèses", ""]
L += [f"- **{i.code}** ({i.severity}) : {i.message}" for i in r.missing_data]
L += ["", "## Préférences", "", "| Préférence | Satisfaites | Non satisfaites |", "|---|---:|---:|"]
L += [f"| {k} | {v['satisfaites']} | {v['non_satisfaites']} |" for k, v in sorted(r.preferences.items())]
L += ["", "## Objectifs (coût pondéré) et poids utilisés", "", "| Terme | Coût | Poids |", "|---|---:|---:|"]
L += [f"| {k} | {v} | {r.weights.get(k, '')} |" for k, v in r.objective.items()]
L += ["", f"Conflits chevauchement/repos évités par le modèle : {r.avoided_violations}"]
out = Path(sys.argv[1] if len(sys.argv) > 1 else "../../docs/simulation-2026-11.md")
out.write_text("\n".join(L) + "\n", encoding="utf-8")
print("écrit", out)
