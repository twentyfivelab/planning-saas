"""Équité des heures mensuelles (19/11/2026) : base équilibrée entre collaborateurs comparables, sans priorité automatique (poids
d'allocation, ancienneté, mérite) ; unités cohérentes avec les objectifs contractuels ; renfort hors part équitable ; moteur et
évaluateur indépendant identiques."""
from datetime import date, time, timedelta

from planning_solver import solve
from planning_solver.context import fairness_units, prepare, water_fill
from planning_solver.model import DEFAULT_WEIGHTS, REINFORCE, Contract, Employee, PRIORITY, Slot, SolverConfig, SolverInput
from planning_solver.objective import evaluate
from planning_solver.weights import engine_weights

DAYS = [date(2026, 11, 2) + timedelta(days=k) for k in range(28)]


def slot(sid, d, brand="A", mandatory=True):
    tmp = Slot(sid, d, "S", time(9), time(18), 60, {brand: 0}, mandatory=mandatory)
    return Slot(sid, d, "S", time(9), time(18), 60, {brand: tmp.effective_minutes}, mandatory=mandatory)


def emp(eid, brands=("A",), level=PRIORITY, **kw):
    return Employee(eid, eid.capitalize(), {b: level for b in brands}, **kw)


def hours(res, eid):
    return sum(a.effective_minutes for a in res.assignments if a.employee_id == eid) // 60


def cfg():
    return SolverConfig(time_limit_s=20, workers=4)


def test_poids_d_allocation_sans_priorite_automatique():
    """Deux paires de collaborateurs identiques, l'un à 1,25 et l'autre à 0,75 : mêmes heures (à un shift près)."""
    slots = [slot(f"a{i}", d) for i, d in enumerate(DAYS)] + [slot(f"b{i}", d) for i, d in enumerate(DAYS)]
    emps = [emp("haut", weight=1.25), emp("bas", weight=0.75), emp("moyen1"), emp("moyen2")]
    res = solve(SolverInput(DAYS[0], DAYS[-1], slots, emps, [], config=cfg()))
    h = {e.id: hours(res, e.id) for e in emps}
    assert max(h.values()) - min(h.values()) <= 8, h
    assert engine_weights()["individual"] == 0 and DEFAULT_WEIGHTS["individual"] == 0  # désactivée par défaut
    assert engine_weights({"individual_priority": 20})["individual"] == 1  # activable explicitement


def test_manque_partage_entre_collaborateurs_comparables():
    """Un petit volume (10 shifts) pour trois collaborateurs comparables qui pourraient chacun en faire 28 : réparti (3-4 chacun),
    jamais tout à l'un et rien aux autres (l'écart progressif rend cette concentration plus coûteuse)."""
    slots = [slot(f"s{i}", d) for i, d in enumerate(DAYS[:10])]
    emps = [emp("ana"), emp("ben"), emp("cleo")]
    inp = SolverInput(DAYS[0], DAYS[-1], slots, emps, [], config=cfg())
    res = solve(inp)
    h = sorted(hours(res, e.id) for e in emps)
    assert h[-1] - h[0] <= 8 and sum(h) == 80, h
    assert fairness_units(10) == 10 and fairness_units(40) == 48 and fairness_units(100) == 188  # progressif au-delà de 16 h et 40 h


def test_objectif_contractuel_et_collaborateurs_sans_objectif_memes_unites():
    """Un objectif contractuel (minutes) et des collaborateurs sans objectif : ces derniers ne sont jamais réduits à rien."""
    slots = [slot(f"s{i}", d) for i, d in enumerate(DAYS)] + [slot(f"t{i}", d) for i, d in enumerate(DAYS[:20])]
    emps = [emp("contrat", contract=Contract(monthly_target_minutes=120 * 60)), emp("libre1"), emp("libre2")]
    inp = SolverInput(DAYS[0], DAYS[-1], slots, emps, [], config=cfg())
    prep = prepare(inp)
    assert all(prep.targets[e] > 60 * 60 for e in ("libre1", "libre2")), prep.targets  # même unité (minutes) pour tous
    res = solve(inp)
    assert min(hours(res, "libre1"), hours(res, "libre2")) >= 100, {e.id: hours(res, e.id) for e in emps}


def test_renfort_hors_part_equitable_et_evaluateur_identique():
    slots = [slot(f"s{i}", d) for i, d in enumerate(DAYS[:20])]
    emps = [emp("titulaire"), emp("titulaire2"), emp("renfort", level=REINFORCE)]
    inp = SolverInput(DAYS[0], DAYS[-1], slots, emps, [], config=cfg())
    prep = prepare(inp)
    assert prep.targets["renfort"] == 0 and prep.fair_ref["renfort"] == 0  # dernier recours : aucune part attendue
    res = solve(inp)
    assert hours(res, "renfort") == 0 and abs(hours(res, "titulaire") - hours(res, "titulaire2")) <= 8
    ev = evaluate(inp, res.assignments)
    assert ev.get("fairness", 0) == res.objective.get("fairness", 0)  # même calcul que le moteur


def test_part_equitable_redistribue_l_excedent_des_collaborateurs_limites():
    t = water_fill(300, {"a": 100, "b": 100, "c": 100}, {"a": 50, "b": 500, "c": 500})
    assert t["a"] == 50 and abs(t["b"] - 125) <= 1 and abs(t["c"] - 125) <= 1  # l'excédent de « a » revient aux autres
    assert sum(water_fill(10_000, {"a": 1, "b": 1}, {"a": 40, "b": 60}).values()) == 100  # jamais au-delà des capacités
