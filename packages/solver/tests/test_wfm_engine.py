"""Moteur WFM : évaluateur indépendant, hiérarchie, missions prioritaires, relations, remplaçants, explications, indicateurs, performance."""
import random
import time as _time
from datetime import date, time, timedelta

import pytest

from planning_solver import solve
from planning_solver.explain import explain_assignment
from planning_solver.metrics import plan_metrics
from planning_solver.model import (Assignment, BrandBudget, Contract, DEFAULT_WEIGHTS, Employee, PRIORITY, REINFORCE, Relation, SECONDARY, Slot,
                                   SolverConfig, SolverInput)
from planning_solver.objective import Evaluator, evaluate
from planning_solver.replace import rank_replacements
from planning_solver.strategies import STRATEGIES, apply_strategy
from planning_solver.validator import validate

D0 = date(2026, 11, 2)  # lundi


def slot(sid, d, site="S", start=(9, 0), end=(18, 0), brand="A", tag="day", **kw):
    return Slot(sid, d, site, time(*start), time(*end), 60, {brand: 480}, tag=tag, **kw)


def emp(eid, brands=None, **kw):
    return Employee(eid, eid.capitalize(), brands if brands is not None else {"A": PRIORITY}, **kw)


def cfg(**kw):
    kw.setdefault("time_limit_s", 20)
    kw.setdefault("workers", 4)
    return SolverConfig(**kw)


def rich_instance(hierarchical=False):
    """Petite instance où tous les types de coût sont actifs ; assez petite pour une preuve d'optimalité."""
    days = [D0 + timedelta(days=k) for k in range(7)]
    slots = []
    for d in days:
        slots.append(slot(f"G-m|{d}", d, "G", (6, 0), (15, 0), "A", tag="open", stagger_group="cos"))
        slots.append(slot(f"G-s|{d}", d, "G", (12, 0), (21, 0), "A", tag="close", stagger_group="cos"))
        if d.weekday() < 5:
            slots.append(slot(f"V|{d}", d, "V", (9, 0), (18, 0), "B", mandatory=d.weekday() != 4, stagger_group="cos"))
    employees = [
        emp("anna", {"A": PRIORITY, "B": SECONDARY}, weight=1.25, time_pref="matin", contract=Contract(monthly_target_minutes=1920, hourly_cost_cents=3000)),
        emp("bea", {"A": PRIORITY}, time_pref="soir", opposite_of="carl", weekly_rest_days_pref=2, sunday_quota=1, sunday_mode="exact"),
        emp("carl", {"A": PRIORITY, "B": REINFORCE}, opposite_of="bea", preferred_tags={"open"}, preference_strength=2, rest_weekdays_soft={2}),
        emp("dina", {"B": PRIORITY, "A": REINFORCE}, weight=0.75, preferred_sites={"V"}, relations=[Relation("work_together", "anna")]),
        emp("emil", {"A": SECONDARY, "B": PRIORITY}, latest_start=time(10, 0), relations=[Relation("avoid_together", "bea"), Relation("mentor", "anna")]),
    ]
    return SolverInput(days[0], days[-1], slots, employees, [BrandBudget("A", 100 * 60, strict=False), BrandBudget("B", 40 * 60)],
                       cfg(hierarchical=hierarchical), previous={f"G-m|{days[0]}": "anna", f"V|{days[1]}": "emil"})


def test_evaluateur_identique_au_solveur_a_l_optimum():
    """Coût recalculé sans CP-SAT = coût du solveur : le même objectif est évalué par deux implémentations indépendantes."""
    inp = rich_instance(hierarchical=False)
    res = solve(inp)
    assert res.proved_optimal and res.levels[0]["proved_optimal"]
    terms = evaluate(inp, res.assignments)
    assert sum(terms.values()) == res.levels[0]["value"]
    assert res.objective == {k: terms.get(k, 0) for k in res.objective}


def test_evaluateur_chaque_niveau_de_la_hierarchie():
    inp = rich_instance(hierarchical=True)
    res = solve(inp)
    assert [lv["level"] for lv in res.levels] == ["couverture", "engagements", "equite", "optimisation"]  # D7 : équité avant le reste
    assert res.proved_optimal and all(lv["proved_optimal"] for lv in res.levels)
    terms = evaluate(inp, res.assignments)
    for lv in res.levels:
        assert sum(terms.get(k, 0) for k in lv["terms"]) == lv["value"], lv["level"]


def test_delta_identique_a_un_recalcul_complet():
    inp = rich_instance()
    res = solve(inp)
    ev = Evaluator(inp, res.assignments)
    rnd = random.Random(7)
    ids = [e.id for e in inp.employees]
    for s in rnd.sample(inp.slots, 12):
        for new in [*rnd.sample(ids, 2), None]:
            after = [a for a in res.assignments if a.slot_id != s.id]
            if new is not None:
                h = s.hours
                after.append(Assignment(s.id, new, s.day, s.start, s.end, h.presence_minutes, h.break_minutes, h.effective_minutes, dict(s.allocations)))
            full, before = evaluate(inp, after), ev.terms()
            assert ev.terms_after(s.id, new) == full, (s.id, new)
            assert ev.delta(s.id, new) == {k: full.get(k, 0) - before.get(k, 0) for k in set(full) | set(before) if full.get(k, 0) != before.get(k, 0)}


def test_hierarchie_la_couverture_prime_meme_si_les_preferences_pesent_plus():
    """Somme pondérée : un poids de préférence énorme fait renoncer à un shift. Hiérarchie : le shift est couvert quand même."""
    d = D0
    weights = {**DEFAULT_WEIGHTS, "coverage": 1, "time_pref": 5000}
    def build(h):
        return SolverInput(d, d, [slot(f"X|{d}", d, "S", (6, 0), (15, 0)), slot(f"Y|{d}", d, "S", (12, 0), (21, 0))],
                           [emp("anna", time_pref="soir"), emp("bea", time_pref="soir")], [], cfg(weights=weights, hierarchical=h))
    assert solve(build(False)).uncovered_slots == [f"X|{d}"]
    r = solve(build(True))
    assert r.uncovered_slots == [] and not r.hard_violations


def test_hierarchie_les_engagements_passent_avant_le_confort():
    d0 = D0
    days = [d0 + timedelta(days=k) for k in range(4)]
    slots = [slot(f"P|{d}", d, "S") for d in days]
    weights = {**DEFAULT_WEIGHTS, "overtime": 1, "preference": 5000}
    # anna préfère le shift mais dépasserait son objectif contractuel ; bea le prend pour tenir l'engagement
    es = [emp("anna", contract=Contract(monthly_target_minutes=480)), emp("bea", contract=Contract(monthly_target_minutes=1440), preferred_tags={"open"})]
    r = solve(SolverInput(d0, days[-1], slots, es, [], cfg(weights=weights)))
    assert r.objective.get("overtime", 0) == 0
    assert sum(a.effective_minutes for a in r.assignments if a.employee_id == "anna") <= 480


def test_mission_prioritaire_couverte_en_premier():
    d = D0
    slots = [slot("permanent", d, "S", (9, 0), (18, 0), priority=3), slot("mission", d, "E", (9, 0), (18, 0), priority=5, mission="M1")]
    r = solve(SolverInput(d, d, slots, [emp("anna")], [], cfg()))
    assert [a.slot_id for a in r.assignments] == ["mission"]
    assert r.uncovered_slots == ["permanent"]
    r2 = solve(SolverInput(d, d, [slot("permanent", d, "S", priority=4), slot("mission", d, "E", priority=2)], [emp("anna")], [], cfg()))
    assert [a.slot_id for a in r2.assignments] == ["permanent"]


def test_qualification_obligatoire_jamais_contournee():
    d = D0
    s = slot("event", d, "E", required_skills=("anglais", "formation-luxe"))
    r = solve(SolverInput(d, d, [s], [emp("anna", skills={"anglais"}), emp("bea", skills={"anglais", "formation-luxe"})], [], cfg()))
    assert [a.employee_id for a in r.assignments] == ["bea"]
    r = solve(SolverInput(d, d, [s], [emp("anna", skills={"anglais"})], [], cfg()))
    assert r.uncovered_slots == ["event"] and r.assignments == []
    assert any(i.code == "NO_CANDIDATE" for i in r.diagnostics)


def test_relation_stricte_eviter_ensemble():
    d = D0
    slots = [slot("a", d), slot("b", d, start=(10, 0), end=(19, 0))]
    es = [emp("anna", relations=[Relation("avoid_together", "bea", strict=True)]), emp("bea")]
    r = solve(SolverInput(d, d, slots, es, [], cfg()))
    assert len(r.assignments) == 1 and len(r.uncovered_slots) == 1  # préfère un poste non couvert à une règle stricte violée
    forced = [Assignment(s.id, e.id, d, s.start, s.end, 540, 60, 480, dict(s.allocations)) for s, e in zip(slots, es)]
    assert any(v.startswith("RELATION_AVOID") for v in validate(SolverInput(d, d, slots, es, [], cfg()), forced))


def test_relation_souple_eviter_ensemble_pas_de_blocage():
    d = D0
    es = [emp("anna", relations=[Relation("avoid_together", "bea")]), emp("bea")]
    r = solve(SolverInput(d, d, [slot("a", d), slot("b", d, start=(10, 0), end=(19, 0))], es, [], cfg()))
    assert len(r.assignments) == 2 and r.objective["family"] == DEFAULT_WEIGHTS["family"]


def test_relation_binome_preferee():
    days = [D0, D0 + timedelta(days=1)]
    slots = [slot(f"s{i}|{d}", d, "S", (9 + i, 0), (18 + i, 0)) for d in days for i in range(1)] + [slot(f"t|{d}", d, "S", (10, 0), (19, 0), mandatory=False) for d in days]
    es = [emp("anna", relations=[Relation("work_together", "bea")]), emp("bea")]
    r = solve(SolverInput(days[0], days[1], slots, es, [BrandBudget("A", 32 * 60)], cfg()))
    assert not r.hard_violations
    a = {x.day for x in r.assignments if x.employee_id == "anna"}
    b = {x.day for x in r.assignments if x.employee_id == "bea"}
    assert a == b


def test_tuteur_obligatoire_nouveau_jamais_seul():
    d = D0
    slots = [slot("a", d), slot("b", d, start=(10, 0), end=(19, 0))]
    es = [emp("novice", relations=[Relation("mentor", "senior", strict=True), Relation("mentor", "autre", strict=True)]), emp("senior", {"B": PRIORITY}), emp("autre", {"A": PRIORITY}, unavailable_dates={d})]
    r = solve(SolverInput(d, d, slots, es, [], cfg()))
    assert all(a.employee_id != "novice" for a in r.assignments)  # aucun tuteur possible ce jour : le nouveau ne travaille pas
    es[2].unavailable_dates = set()
    r = solve(SolverInput(d, d, slots, es, [], cfg()))
    assert {a.employee_id for a in r.assignments} == {"novice", "autre"} and not r.hard_violations


def test_jours_de_repos_et_sites_stricts_et_souples():
    d = D0  # lundi
    s = slot("x", d)
    assert solve(SolverInput(d, d, [s], [emp("anna", rest_weekdays_hard={0})], [], cfg())).assignments == []
    assert solve(SolverInput(d, d, [s], [emp("anna", allowed_sites={"Autre"})], [], cfg())).assignments == []
    r = solve(SolverInput(d, d, [s], [emp("anna", rest_weekdays_soft={0}), emp("bea", preferred_sites={"Autre"}), emp("carl")], [], cfg()))
    assert r.assignments[0].employee_id == "carl"  # les deux autres auraient une préférence non respectée
    forced = [Assignment("x", "anna", d, s.start, s.end, 540, 60, 480, dict(s.allocations))]
    v = validate(SolverInput(d, d, [s], [emp("anna", rest_weekdays_hard={0}, allowed_sites={"Autre"})], [], cfg()), forced)
    assert any(x.startswith("REST_WEEKDAY") for x in v) and any(x.startswith("SITE_NOT_ALLOWED") for x in v)


def test_equite_proportionnelle_aux_contrats():
    """40 h et 20 h par semaine : chacun approche SON objectif, pas un volume identique."""
    days = [D0 + timedelta(days=k) for k in range(6)]
    slots = [slot(f"s|{d}", d) for d in days]
    es = [emp("plein", contract=Contract(monthly_target_minutes=4 * 480)), emp("partiel", contract=Contract(monthly_target_minutes=2 * 480))]
    r = solve(SolverInput(days[0], days[-1], slots, es, [], cfg()))
    assert r.employee_hours == {"plein": 4 * 480, "partiel": 2 * 480}
    rows = {x["id"]: x for x in r.metrics["employees"]}
    assert rows["plein"]["attainment"] == 100.0 and rows["partiel"]["attainment"] == 100.0 and rows["plein"]["gap_minutes"] == 0


def test_cout_uniquement_si_renseigne_et_jamais_suppose():
    d = D0
    s = slot("x", d)
    r = solve(SolverInput(d, d, [s], [emp("cher", contract=Contract(hourly_cost_cents=5000)), emp("moins", contract=Contract(hourly_cost_cents=3000))], [], cfg()))
    assert r.assignments[0].employee_id == "moins"
    assert r.metrics["cost_cents"] == 3000 * 8 and r.metrics["cost_known_share"] == 100.0
    r = solve(SolverInput(d, d, [s], [emp("sans")], [], cfg()))
    assert r.metrics["cost_cents"] is None and "cost" not in r.objective  # aucun coût inventé


def test_co_branding_une_journee_deux_budgets():
    d = D0
    s = Slot("cn", d, "CN", time(9, 0), time(18, 0), 60, {"Nuxe": 240, "Cellcosmet": 240})
    r = solve(SolverInput(d, d, [s], [emp("jane", {"Nuxe": PRIORITY, "Cellcosmet": PRIORITY})], [BrandBudget("Nuxe", 240), BrandBudget("Cellcosmet", 240)], cfg()))
    assert r.employee_hours == {"jane": 480}
    assert r.metrics["by_brand"] == {"Nuxe": 240, "Cellcosmet": 240} and r.metrics["employees"][0]["days"] == 1
    assert not r.hard_violations


def test_verificateur_recalcule_les_heures_et_imputations():
    d = D0
    s = slot("x", d)
    bad = [Assignment("x", "anna", d, s.start, s.end, 540, 60, 500, dict(s.allocations))]
    assert any(v.startswith("HOURS_MISMATCH") for v in validate(SolverInput(d, d, [s], [emp("anna")], [], cfg()), bad))
    bad = [Assignment("x", "anna", d, s.start, s.end, 540, 60, 480, {"A": 400})]
    assert any(v.startswith("ALLOCATION_MISMATCH") for v in validate(SolverInput(d, d, [s], [emp("anna")], [], cfg()), bad))


def _absence_case():
    days = [D0 + timedelta(days=k) for k in range(5)]
    slots = [slot(f"g|{d}", d, "G", (9, 0), (18, 0)) for d in days]
    slots += [slot(f"v|{d}", d, "V", (9, 0), (18, 0), "B") for d in days]
    es = [emp("kristina", {"A": PRIORITY}), emp("sahra", {"A": PRIORITY, "B": PRIORITY}, time_pref="soir"), emp("renfort", {"A": REINFORCE}), emp("marc", {"B": PRIORITY}),
          emp("hors", {"Z": PRIORITY}), emp("occupee", {"A": PRIORITY}, unavailable_dates={days[2]}), emp("sans", {"A": PRIORITY}, skills=set())]
    plan = []
    for d in days:
        for sid, who in ((f"g|{d}", "kristina"), (f"v|{d}", "marc")):
            s = next(x for x in slots if x.id == sid)
            plan.append(Assignment(sid, who, d, s.start, s.end, 540, 60, 480, dict(s.allocations)))
    return SolverInput(days[0], days[-1], slots, es, [], cfg()), plan, days


def test_remplacants_classes_par_cout_reel_et_justifies():
    inp, plan, days = _absence_case()
    sid = f"g|{days[2]}"
    r = rank_replacements(inp, plan, sid)
    by = {c["name"]: c for c in r["candidates"]}
    assert r["holder"] == "kristina" and "Kristina" not in by
    assert by["Hors"]["status"] == "impossible" and by["Hors"]["blocking"][0]["code"] == "BRAND_NOT_ELIGIBLE"
    assert by["Occupee"]["status"] == "impossible" and by["Occupee"]["blocking"][0]["code"] == "UNAVAILABLE" and by["Occupee"]["available"] is False
    ok = [c for c in r["candidates"] if c["status"] == "compatible"]
    assert ok == sorted(ok, key=lambda c: c["delta_cost"]) and ok[0]["score"] == 100 and ok[-1]["score"] == 0
    assert by["Renfort"]["delta_cost"] > by["Sans"]["delta_cost"]  # le renfort coûte plus cher qu'un prioritaire libre
    assert any(t["term"] == "reinforce" and t["points"] > 0 for t in by["Renfort"]["terms"])
    assert by["Renfort"]["brand_level_label"] == "Renfort" and by["Sans"]["brand_level_label"] == "Prioritaire"
    assert by["Sans"]["minutes"] == 0 and by["Sans"]["after_minutes"] == 480
    # le classement correspond exactement au coût du planning après remplacement
    base = evaluate(inp, plan)
    s = next(x for x in inp.slots if x.id == sid)
    after = [a for a in plan if a.slot_id != sid] + [Assignment(sid, by["Renfort"]["employee_id"], s.day, s.start, s.end, 540, 60, 480, dict(s.allocations))]
    assert sum(evaluate(inp, after).values()) - sum(base.values()) == by["Renfort"]["delta_cost"]


def test_remplacant_ecarte_si_repos_insuffisant():
    d0, d1 = D0, D0 + timedelta(days=1)
    close = slot(f"soir|{d0}", d0, "G", (12, 0), (21, 0), tag="close")
    open_ = slot(f"matin|{d1}", d1, "G", (6, 0), (15, 0), tag="open")
    plan = [Assignment(close.id, "bea", d0, close.start, close.end, 540, 60, 480, dict(close.allocations)), Assignment(open_.id, "anna", d1, open_.start, open_.end, 540, 60, 480, dict(open_.allocations))]
    inp = SolverInput(d0, d1, [close, open_], [emp("anna"), emp("bea"), emp("carl")], [], cfg())
    r = rank_replacements(inp, plan, open_.id)
    by = {c["name"]: c for c in r["candidates"]}
    assert by["Bea"]["status"] == "impossible" and "REST" in by["Bea"]["blocking"][0]["code"]
    assert by["Carl"]["status"] == "compatible"


def test_explication_basee_sur_les_vraies_donnees():
    inp, plan, days = _absence_case()
    sid = f"g|{days[1]}"
    ex = explain_assignment(inp, plan, sid)
    assert ex["employee"] == "Kristina" and ex["all_rules_ok"] is True
    codes = {c["code"]: c for c in ex["checks"]}
    assert codes["BRAND"]["detail"] == "A : Prioritaire" and codes["CONSECUTIVE"]["detail"] == "Série en cours : 5 jours"
    assert "cause unique" in ex["caveat"]
    assert any(o["label"] == "Niveau sur A" and o["tone"] == "favorable" for o in ex["observed"])
    assert ex["compatible_candidates"] >= 2 and ex["alternatives"][0]["extra_cost"] <= ex["alternatives"][-1]["extra_cost"]
    # un shift pris en dérogation : l'explication le montre, sans inventer de justification
    inp.employees[0].unavailable_dates = {days[1]}
    ex = explain_assignment(inp, plan, sid)
    assert ex["all_rules_ok"] is False and not {c["code"]: c for c in ex["checks"]}["AVAILABLE"]["ok"]


def test_indicateurs_et_comparaison_avec_un_planning_de_reference():
    inp, plan, days = _absence_case()
    ref = {a.slot_id: a.employee_id for a in plan}
    moved = [a if a.slot_id != f"g|{days[0]}" else Assignment(a.slot_id, "sans", a.day, a.start, a.end, 540, 60, 480, dict(a.allocations)) for a in plan[1:]]
    m = plan_metrics(inp, moved, reference=ref)
    assert m["mandatory_shifts"] == 10 and m["uncovered_shifts"] == 1 and m["coverage_rate"] == 90.0
    assert m["changes"] == {"added": 0, "removed": 1, "changed": 0, "total": 1, "unchanged": 9}
    k = {r["id"]: r for r in m["employees"]}["kristina"]
    assert k["days"] == 4 and k["max_consecutive"] == 4 and k["sundays"] == 0


def test_statut_jamais_optimal_sans_preuve():
    from planning_solver.demo_nov2026 import build_input
    inp = build_input(); inp.config = SolverConfig(time_limit_s=1.5, workers=2)
    r = solve(inp)
    assert r.proved_optimal is False or all(lv["proved_optimal"] for lv in r.levels)
    assert r.status != "optimal" or r.proved_optimal
    assert all("proved_optimal" in lv for lv in r.levels)


def test_verrou_impossible_diagnostique_nommement():
    d = D0
    s = slot("x", d)
    r = solve(SolverInput(d, d, [s], [emp("anna", unavailable_dates={d}), emp("bea")], [], cfg(), locked={"x": "anna"}))
    assert r.status == "infaisable"
    lock = next(i for i in r.diagnostics if i.code == "LOCK_IMPOSSIBLE")
    assert "Anna" in lock.message and "indisponible" in lock.message and lock.slots == ["x"]


def test_perimetre_fige_shift_vide_reste_vide_et_stabilite():
    """Réoptimisation locale : un shift hors périmètre reste vide, même si le pourvoir améliorerait la couverture."""
    d = D0
    a, b = slot("a", d), slot("b", d, "E")
    r = solve(SolverInput(d, d, [a, b], [emp("anna"), emp("bea")], [], cfg(), frozen_empty={"b"}))
    assert [x.slot_id for x in r.assignments] == ["a"] and r.uncovered_slots == ["b"] and not r.hard_violations


def test_taille_du_modele_prefiltrage():
    d = D0
    r = solve(SolverInput(d, d, [slot("a", d), slot("b", d, brand="B")], [emp("anna"), emp("bea", {"B": PRIORITY})], [], cfg()))
    assert r.model == {"employees": 2, "shifts": 2, "possible_pairs": 4, "decision_variables": 2, "filtered_out": 2}


def test_pause_du_referentiel_juridique():
    d = D0
    short = Slot("court", d, "S", time(9, 0), time(18, 0), 15, {"A": 525})
    ok = Slot("ok", d, "T", time(9, 0), time(18, 0), 60, {"A": 480})
    rules = [(330, 15), (420, 30), (540, 60)]
    r = solve(SolverInput(d, d, [short, ok], [emp("anna"), emp("bea")], [], cfg(break_rules=rules)))
    assert [x.slot_id for x in r.assignments] == ["ok"]  # 8 h 45 de travail : 30 min exigées, 15 min prévues -> jamais pourvu
    assert any(i.code == "BREAK_RULE" and i.slots == ["court"] for i in r.missing_data)
    h = short.hours
    forced = [Assignment("court", "anna", d, short.start, short.end, h.presence_minutes, h.break_minutes, h.effective_minutes, dict(short.allocations))]
    assert any(v.startswith("BREAK_TOO_SHORT") for v in validate(SolverInput(d, d, [short], [emp("anna")], [], cfg(break_rules=rules)), forced))


def test_plafond_hebdomadaire_legal_avec_semaine_a_cheval():
    """Le plafond compte les heures de la période voisine dans la même semaine ISO."""
    from planning_solver.model import OutsideShift
    days = [date(2026, 12, 1), date(2026, 12, 2)]  # mardi, mercredi ; lundi 30 novembre : période voisine
    slots = [slot(f"s|{d}", d) for d in days]
    anna = emp("anna", legal_weekly_max_minutes=16 * 60)
    out = [OutsideShift("anna", date(2026, 11, 30), time(9, 0), time(18, 0), 480)]
    r = solve(SolverInput(days[0], days[1], slots, [anna], [], cfg(), outside_shifts=out))
    assert len(r.assignments) == 1 and r.employee_hours == {"anna": 480} and not r.hard_violations


def test_strategies_changent_les_poids_pas_les_regles():
    w = dict(DEFAULT_WEIGHTS)
    assert apply_strategy(w, "couverture") == w
    assert apply_strategy(w, "equite")["fairness"] == w["fairness"] * 4
    assert {s["key"] for s in STRATEGIES} == {"couverture", "equite", "preferences", "marques", "cout", "stabilite"}
    from planning_solver.demo_nov2026 import build_input
    base = build_input()
    runs = {}
    for key in ("couverture", "equite"):
        inp = build_input(); inp.config = SolverConfig(time_limit_s=6, workers=4)
        inp.config.weights = apply_strategy(base.config.weights, key)
        runs[key] = solve(inp)
        assert not runs[key].hard_violations
    assert runs["equite"].metrics["coverage_rate"] == runs["couverture"].metrics["coverage_rate"]  # même couverture : la hiérarchie la garantit


def large_instance(n_emp=150, n_days=30):
    rnd = random.Random(42)
    days = [date(2027, 3, 1) + timedelta(days=k) for k in range(n_days)]
    sites = [f"S{i}" for i in range(12)]
    brands = [f"B{i}" for i in range(12)]
    slots = []
    for i, st in enumerate(sites):
        for d in days:
            for h, tag in (((6, 0), "open"), ((10, 0), "day"), ((12, 0), "close")):
                for k in range(2):
                    slots.append(Slot(f"{st}-{h[0]}-{k}|{d}", d, st, time(*h), time(h[0] + 9, h[1]), 60, {brands[i]: 480}, tag=tag))
    es = []
    for i in range(n_emp):
        allowed = rnd.sample(brands, 3)
        es.append(Employee(f"e{i:03d}", f"Collaborateur {i}", {b: rnd.choice([PRIORITY, PRIORITY, SECONDARY, REINFORCE]) for b in allowed},
                           contract=Contract(monthly_target_minutes=rnd.choice([80, 120, 160]) * 60, monthly_max_minutes=190 * 60),
                           time_pref=rnd.choice([None, "matin", "soir"]), unavailable_dates=set(rnd.sample(days, 3)), weight=rnd.choice([0.75, 1, 1.25])))
    return SolverInput(days[0], days[-1], slots, es, [], SolverConfig(time_limit_s=25, workers=4))


class _Spy:
    def __init__(self, real):
        self.real, self.calls = real, []

    def __call__(self, inp, assignments):
        out = self.real(inp, assignments)
        self.calls.append(len(assignments))
        return out


def test_grand_effectif_resultat_toujours_valide_et_statut_honnete(monkeypatch):
    """Test de CORRECTION (pas une mesure de temps) : 150 collaborateurs, 2 160 shifts. Quel que soit le temps disponible ou la charge de la
    machine, le résultat est soit un planning entièrement vérifié et sans violation, soit « interrompu » sans aucune affectation ; jamais un
    optimum annoncé sans preuve, jamais un niveau prouvé sans solution."""
    from planning_solver import engine
    spy = _Spy(engine.validate)
    monkeypatch.setattr(engine, "validate", spy)
    inp = large_instance()
    inp.config.time_limit_s = 20
    r = solve(inp)
    if r.status == "interrompu":
        assert r.assignments == [] and spy.calls == []
        return
    assert r.hard_violations == [] and spy.calls == [len(r.assignments)] and r.assignments
    assert r.metrics["uncovered_shifts"] == len(r.uncovered_slots)
    assert r.proved_optimal == all(x["proved_optimal"] for x in r.levels) and (r.status == "optimal") == r.proved_optimal
    assert all(x["value"] is not None or not x["proved_optimal"] for x in r.levels)


@pytest.mark.perf
def test_performance_grand_effectif(monkeypatch):
    """MESURE DE PERFORMANCE (marqueur perf, exécutée à part dans des conditions documentées : scripts/ops/perf_engine.sh).
    150 collaborateurs, 30 jours, 2 160 shifts : tous les niveaux s'exécutent dans le délai, couverture complète prouvée, statut honnête."""
    from planning_solver import engine
    spy = _Spy(engine.validate)
    monkeypatch.setattr(engine, "validate", spy)
    inp = large_instance()
    inp.config.time_limit_s = 45  # budget du produit pour cette taille ; sur une machine disponible, la couverture est prouvée en moins de 10 s
    t0 = _time.time()
    r = solve(inp)
    took = _time.time() - t0
    t = r.timing
    print(f"TIMING model_s={t['model_s']} search_s={t['search_s']} post_s={t['post_s']} engine_total_s={t['engine_total_s']} time_limit_s={t['time_limit_s']}")
    assert took < 90, f"{took:.1f}s"
    # la durée maximale borne la construction du modèle et la recherche (dépassement mesuré : quelques dixièmes de seconde)
    assert t["model_s"] + t["search_s"] <= t["time_limit_s"] + 1.0, t
    assert r.hard_violations == []
    assert r.metrics["coverage_rate"] == 100.0 and r.uncovered_slots == []  # la capacité dépasse largement la demande : aucun manque n'est acceptable ici
    lv = {x["level"]: x for x in r.levels}
    assert lv["couverture"]["value"] == 0 and lv["couverture"]["proved_optimal"] is True
    assert lv["optimisation"]["value"] is not None  # l'équité et les préférences ont bien été optimisées, pas seulement la couverture
    assert r.objective["fairness"] > 0 and "time_pref" in r.objective
    assert r.status == "faisable" and r.proved_optimal is False  # optimum non prouvé à cette taille : jamais annoncé comme tel
    assert spy.calls == [2160]  # solution valide sans preuve : vérifiée elle aussi, sur les 2 160 affectations


def test_grand_effectif_capacite_insuffisante_manques_expliques():
    """Effectif volontairement trop faible : les manques sont réels, listés et expliqués, le planning reste valide."""
    inp = large_instance(n_emp=70, n_days=14)
    inp.config.time_limit_s = 15
    r = solve(inp)
    assert r.hard_violations == []
    assert r.status == "partiellement_couvert" and r.uncovered_slots
    assert r.metrics["uncovered_shifts"] == len(r.uncovered_slots) < r.metrics["mandatory_shifts"]
    assert any(i.code in ("COMBINED_CONSTRAINTS", "NO_CANDIDATE") for i in r.diagnostics)


def test_validateur_execute_pour_chaque_statut_de_planning(monkeypatch):
    """Optimal, partiel, interrompu : le vérificateur indépendant s'exécute à chaque fois (cas « valide sans preuve » : test de performance) ; sans planning, rien à vérifier."""
    import threading
    from planning_solver import engine
    spy = _Spy(engine.validate)
    monkeypatch.setattr(engine, "validate", spy)
    d = D0
    cases = {}
    r = solve(SolverInput(d, d, [slot("a", d)], [emp("anna")], [], cfg()))
    cases["optimal"] = r
    r = solve(SolverInput(d, d, [slot("a", d), slot("b", d, "E")], [emp("anna")], [], cfg()))
    cases["partiellement_couvert"] = r
    stop = threading.Event()
    stop.set()
    cases["interrompu"] = solve(SolverInput(d, d, [slot("a", d)], [emp("anna")], [], cfg()), stop)
    assert cases["optimal"].status == "optimal" and cases["partiellement_couvert"].status == "partiellement_couvert"
    assert cases["interrompu"].status == "interrompu"
    assert len(spy.calls) == sum(1 for c in cases.values() if c.assignments or c.status != "interrompu")
    assert all(n >= 0 for n in spy.calls)
    before = len(spy.calls)
    r = solve(SolverInput(d, d, [slot("a", d)], [emp("anna", unavailable_dates={d})], [], cfg(), locked={"a": "anna"}))
    assert r.status == "infaisable" and r.assignments == [] and len(spy.calls) == before  # aucun planning produit, rien à vérifier


def test_une_violation_detectee_rend_le_planning_non_validable(monkeypatch):
    from planning_solver import engine
    monkeypatch.setattr(engine, "validate", lambda inp, a: ["FAUX: violation de test"])
    d = D0
    r = solve(SolverInput(d, d, [slot("a", d)], [emp("anna", contract=Contract())], [], cfg()))
    assert r.hard_violations == ["FAUX: violation de test"] and r.validable is False


def test_validateur_refuse_un_shift_hors_perimetre():
    d = D0
    s = slot("b", d)
    bad = [Assignment("b", "anna", d, s.start, s.end, 540, 60, 480, dict(s.allocations))]
    assert any(v.startswith("FROZEN_SLOT") for v in validate(SolverInput(d, d, [s], [emp("anna")], [], cfg(), frozen_empty={"b"}), bad))


def test_verrou_sur_un_shift_disparu_explique_sans_identifiant_interne():
    """Shift verrouillé dont l'animation n'existe plus dans le mois (marque désactivée…) : calcul infaisable, message lisible (date)."""
    d = date(2026, 12, 5)
    s = Slot(f"X|{d}", d, "S1", time(9), time(17), 0, {"A": 480})
    inp = SolverInput(d, d, [s], [Employee("ana", "Ana", {"A": PRIORITY})], [], SolverConfig(time_limit_s=5, workers=2),
                      locked={"CARTIER-SOIR|2026-12-05": "ana"})
    r = solve(inp)
    assert r.status == "infaisable"
    msg = next(i.message for i in r.diagnostics if i.code == "LOCK_IMPOSSIBLE")
    assert "du 05/12/2026" in msg and "(Ana)" in msg and "n'existe plus dans la configuration de ce mois" in msg and "|" not in msg
