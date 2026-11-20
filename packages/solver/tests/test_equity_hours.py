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


def test_renfort_inclus_dans_la_cible_et_evaluateur_identique():
    """Décision D7 (20/11/2026) : être uniquement en renfort n'exclut pas de la cible commune ; l'équité passe avant la préférence d'éviter
    le renfort. 20 shifts (160 h) pour deux titulaires et un collaborateur en renfort : mêmes heures pour les trois (à un shift près)."""
    slots = [slot(f"s{i}", d) for i, d in enumerate(DAYS[:20])]
    emps = [emp("titulaire"), emp("titulaire2"), emp("renfort", level=REINFORCE)]
    inp = SolverInput(DAYS[0], DAYS[-1], slots, emps, [], config=SolverConfig(time_limit_s=20, workers=4, hierarchical=True))
    prep = prepare(inp)
    assert prep.targets["renfort"] == prep.targets["titulaire"] > 0 and prep.fair_ref["renfort"] == prep.fair_ref["titulaire"]
    res = solve(inp)
    h = sorted(hours(res, e) for e in ("titulaire", "titulaire2", "renfort"))
    assert h[-1] - h[0] <= 8 and hours(res, "renfort") >= 48, h
    ev = evaluate(inp, res.assignments)
    assert ev.get("fairness", 0) == res.objective.get("fairness", 0)  # même calcul que le moteur


def test_part_equitable_redistribue_l_excedent_des_collaborateurs_limites():
    t = water_fill(300, {"a": 100, "b": 100, "c": 100}, {"a": 50, "b": 500, "c": 500})
    assert t["a"] == 50 and abs(t["b"] - 125) <= 1 and abs(t["c"] - 125) <= 1  # l'excédent de « a » revient aux autres
    assert sum(water_fill(10_000, {"a": 1, "b": 1}, {"a": 40, "b": 60}).values()) == 100  # jamais au-delà des capacités


def test_cible_commune_plafonnee_par_la_capacite_et_objectif_explicite():
    """Cible COMMUNE d'heures (et non proportionnelle aux jours possibles) : « restreinte » ne peut travailler que les lundis (4 jours),
    « libre » tous les jours ; 6 shifts à répartir -> 24 h chacune (la capacité de 32 h de « restreinte » n'est pas atteinte).
    Avec un objectif explicite de 16 h, « contrat » reçoit 16 h et le reste est réparti à parts égales entre les autres."""
    from planning_solver.model import Contract
    mondays = [d for d in DAYS if d.weekday() == 0]
    slots = [slot(f"s{i}", d) for i, d in enumerate(mondays)] + [slot(f"t{i}", d) for i, d in enumerate([d for d in DAYS if d.weekday() == 1][:2])]
    emps = [emp("restreinte", unavailable_weekdays={1, 2, 3, 4, 5, 6}), emp("libre")]
    inp = SolverInput(DAYS[0], DAYS[-1], slots, emps, [], config=cfg())
    prep = prepare(inp)
    assert prep.targets["restreinte"] == prep.targets["libre"] == 24 * 60, prep.targets  # même cible, dans la capacité de chacune
    assert prep.fair_cap["restreinte"] == 32 * 60
    res = solve(inp)
    assert hours(res, "restreinte") == hours(res, "libre") == 24
    # objectif explicite (plafonné par la capacité), le reste en parts égales
    emps2 = [emp("contrat", contract=Contract(monthly_target_minutes=16 * 60)), emp("a"), emp("b")]
    slots2 = [slot(f"u{i}", d) for i, d in enumerate(DAYS[:14])]  # 14 shifts = 112 h
    p2 = prepare(SolverInput(DAYS[0], DAYS[-1], slots2, emps2, [], config=cfg()))
    assert p2.targets["contrat"] == 16 * 60 and p2.targets["a"] == p2.targets["b"] == 48 * 60, p2.targets


def test_cible_plafonnee_par_les_shifts_partages():
    """Capacité RÉELLEMENT atteignable compte tenu des autres : « p1 », « p2 », « p3 » ne peuvent travailler que sur la marque B (6 shifts,
    48 h à se partager) ; « x » et « y » sur A (20 shifts, 160 h). Seules, leurs capacités sont identiques (6 jours possibles ou plus),
    mais une cible égale (208 h / 5 ≈ 42 h) est inatteignable pour les trois premières : leur cible est leur part du groupe (16 h), les autres
    se partagent A (80 h). Le moteur et l'évaluateur utilisent les mêmes cibles."""
    from planning_solver.context import realized_targets
    b_slots = [slot(f"b{i}", DAYS[i], brand="B") for i in range(6)]
    a_slots = [slot(f"a{i}", DAYS[i], brand="A") for i in range(20)]
    emps = [emp(f"p{k}", brands=("B",)) for k in (1, 2, 3)] + [emp("x"), emp("y")]
    inp = SolverInput(DAYS[0], DAYS[-1], b_slots + a_slots, emps, [], config=cfg())
    prep = prepare(inp)
    tg, refs = realized_targets(prep, [s.id for s in inp.slots])
    assert {k: tg[k] // 60 for k in ("p1", "p2", "p3", "x", "y")} == {"p1": 16, "p2": 16, "p3": 16, "x": 80, "y": 80}, tg
    assert refs["p1"] == refs["x"] == 80 * 60  # référence affichée : la cible commune
    res = solve(inp)
    assert sorted(hours(res, k) for k in ("p1", "p2", "p3")) == [16, 16, 16] and hours(res, "x") == hours(res, "y") == 80
    ev = evaluate(inp, res.assignments)
    assert ev["fairness"] == 0, ev  # chacun exactement à sa cible atteignable


def test_besoins_optionnels_sans_budget_atteignables_pour_la_cible():
    """« ob » ne peut prendre que des besoins OPTIONNELS sans budget (marque O), « ma » les shifts obligatoires (marque A, 80 h). Le volume
    décidé (80 h, obligatoires) fixe le total des cibles, mais les besoins optionnels sans budget restent atteignables : cible commune
    de 40 h chacun (et non 0 h pour « ob »), et le moteur en retient pour l'en rapprocher."""
    from planning_solver.context import realized_targets
    mand = [slot(f"m{i}", DAYS[2 * i], brand="A") for i in range(10)]  # un jour sur deux : ni série ni repos en jeu
    opt = [slot(f"o{i}", DAYS[2 * i], brand="O", mandatory=False) for i in range(10)]
    inp = SolverInput(DAYS[0], DAYS[-1], mand + opt, [emp("ma", brands=("A",)), emp("ob", brands=("O",))], [], config=cfg())
    prep = prepare(inp)
    tg, _ = realized_targets(prep, [s.id for s in mand])
    assert tg["ma"] == tg["ob"] == 40 * 60, tg
    res = solve(inp)
    assert hours(res, "ma") == 80 and hours(res, "ob") == 40


def test_d7_equite_avant_le_renfort():
    """Décision D7 : « libre » est prioritaire sur A ; « limitee » prioritaire sur B (4 shifts seulement) et en renfort sur A. Avec
    l'ancienne pondération (renfort 12 par heure, écart 3 par demi-heure), « limitee » restait à 32 h. Désormais l'équité passe d'abord :
    elle reçoit des shifts A en renfort jusqu'à des heures égales (à un shift près)."""
    a_slots = [slot(f"a{i}", DAYS[i], brand="A") for i in range(0, 24)]
    b_slots = [slot(f"b{i}", DAYS[i], brand="B") for i in (24, 25, 26, 27)]
    emps = [emp("libre", brands=("A",)), Employee("limitee", "Limitee", {"B": PRIORITY, "A": REINFORCE})]
    inp = SolverInput(DAYS[0], DAYS[-1], a_slots + b_slots, emps, [], config=cfg())
    res = solve(inp)
    assert [lv["level"] for lv in res.levels][-2:] == ["equite", "optimisation"]
    assert abs(hours(res, "libre") - hours(res, "limitee")) <= 8, (hours(res, "libre"), hours(res, "limitee"))


def test_d7_a_equite_egale_le_niveau_de_marque_departage():
    """À répartition d'heures égale, « prioritaire » est préféré au renfort : chacun prend les shifts de la marque où il est prioritaire."""
    a_slots = [slot(f"a{i}", DAYS[2 * i], brand="A") for i in range(4)]
    b_slots = [slot(f"b{i}", DAYS[2 * i + 1], brand="B") for i in range(4)]
    emps = [Employee("pa", "Pa", {"A": PRIORITY, "B": REINFORCE}), Employee("pb", "Pb", {"B": PRIORITY, "A": REINFORCE})]
    res = solve(SolverInput(DAYS[0], DAYS[-1], a_slots + b_slots, emps, [], config=cfg()))
    got = {e: sorted(a.slot_id for a in res.assignments if a.employee_id == e) for e in ("pa", "pb")}
    assert all(s.startswith("a") for s in got["pa"]) and all(s.startswith("b") for s in got["pb"]) and len(got["pa"]) == len(got["pb"]) == 4, got


def test_capacite_avec_limites_hebdomadaires_de_la_fiche():
    """Capacité seul : jours maximum par semaine et plafond d'heures hebdomadaire du contrat comptent (auparavant ignorés). 28 jours
    possibles, au plus 3 jours et 20 h par semaine -> 4 semaines x 20 h = 80 h (et non 224 h)."""
    from planning_solver.context import load_limits
    e = Employee("w", "W", {"A": PRIORITY}, max_days_per_week=3, contract=Contract(weekly_max_minutes=20 * 60))
    _days_, weeks, total = load_limits([slot(f"s{i}", d) for i, d in enumerate(DAYS)], e)
    assert total == 80 * 60 and set(weeks.values()) == {20 * 60}, (total, weeks)
