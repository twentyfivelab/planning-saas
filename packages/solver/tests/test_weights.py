"""Pondérations personnalisables : conversion, influence réelle sur le résultat, contraintes strictes indépendantes."""
from datetime import date, time

from planning_solver.engine import solve
from planning_solver.model import DEFAULT_WEIGHTS, PRIORITY, SECONDARY, BrandBudget, Employee, Slot, SolverConfig, SolverInput
from planning_solver.weights import ADVANCED_KEYS, CRITERIA, DEFAULT_UI, breakdown, engine_weights

D = date(2026, 12, 7)


def slot(sid, day, st, en, site="S"):
    return Slot(sid, day, site, st, en, 60, {"B": (en.hour - st.hour - 1) * 60}, tag="day")


def run(slots, emps, weights, **kw):
    cfg = SolverConfig(time_limit_s=10, workers=1, weights=weights)
    return solve(SolverInput(date(2026, 12, 1), date(2026, 12, 31), slots, emps, [BrandBudget("B", 10 ** 6)], cfg, **kw))


def test_defaults_reproduce_the_historic_engine_weights():
    w = engine_weights()
    for k in ("coverage", "budget", "secondary", "reinforce", "preference", "fairness", "time_pref", "family", "balance"):
        assert w[k] == DEFAULT_WEIGHTS[k]


def test_scale_is_exponential_zero_disables_and_advanced_overrides():
    base = DEFAULT_UI["family"]
    assert engine_weights({"family": base + 20})["family"] == 2 * DEFAULT_WEIGHTS["family"]
    assert engine_weights({"family": base - 20})["family"] < DEFAULT_WEIGHTS["family"]
    assert engine_weights({"family": 0})["family"] == 0
    w = engine_weights({}, {"coverage": 42, "nope": 9, "stability": 10 ** 9})
    assert w["coverage"] == 42 and w["stability"] == 5000 and "nope" not in w


def test_every_criterion_maps_to_a_real_engine_weight():
    for _k, _l, _d, engs, text in CRITERIA:
        assert text and all(e in DEFAULT_WEIGHTS for e in engs)
    assert all(k in DEFAULT_WEIGHTS for k in ADVANCED_KEYS)


def _family_case():
    slots = [slot("a", D, time(8), time(17), "S1"), slot("b", D, time(8), time(17), "S2")]
    emps = [Employee("mila", "Mila", {"B": PRIORITY}, opposite_of="abdu"), Employee("abdu", "Abdu", {"B": PRIORITY}, opposite_of="mila"),
            Employee("cara", "Cara", {"B": SECONDARY})]
    return slots, emps


def test_brand_priority_weight_changes_who_is_assigned_when_several_solutions_are_valid():
    slots, emps = _family_case()
    high = run(slots, emps, engine_weights({"brand_priority": 90, "family": 90}))
    assert {a.employee_id for a in high.assignments} == {"mila", "abdu"}  # priorités de marque respectées
    low = run(slots, emps, engine_weights({"brand_priority": 0, "family": 90}))
    # secondaire gratuit : la préférence familiale (horaires opposés) l'emporte -> Cara prend un des deux shifts
    assert "cara" in {a.employee_id for a in low.assignments}
    assert breakdown(high.objective).get("family", 0) > 0 and breakdown(low.objective).get("family", 0) == 0


def test_family_weight_zero_removes_the_family_cost_from_the_score():
    slots, emps = _family_case()
    r = run(slots, emps, engine_weights({"family": 0}))
    assert breakdown(r.objective).get("family", 0) == 0
    assert r.weights["family"] == 0


def test_a_zero_weight_never_relaxes_a_hard_constraint():
    d2 = date(2026, 12, 8)
    slots = [slot("a", D, time(13), time(22)), slot("b", d2, time(6), time(15))]
    e = Employee("x", "X", {"B": PRIORITY})
    w = {k: 0 for k in DEFAULT_WEIGHTS}
    r = run(slots, [e], {**w, "coverage": 0})
    assert len(r.assignments) <= 1  # repos de 11 h : jamais les deux, même avec tous les poids à 0
    assert not r.hard_violations


def test_fairness_weight_spreads_hours_more_evenly():
    slots = [slot(f"s{i}", date(2026, 12, 1 + i), time(8), time(17)) for i in range(6)]
    emps = [Employee("a", "A", {"B": PRIORITY}), Employee("b", "B", {"B": PRIORITY})]
    r = run(slots, emps, engine_weights({"fairness": 100}))
    n = {e: sum(1 for a in r.assignments if a.employee_id == e) for e in ("a", "b")}
    assert n == {"a": 3, "b": 3}


def test_individual_priority_prefers_the_higher_allocation_weight():
    slots = [slot("s", D, time(8), time(17))]
    emps = [Employee("hi", "Hi", {"B": PRIORITY}, weight=2.0), Employee("lo", "Lo", {"B": PRIORITY}, weight=1.0)]
    r = run(slots, emps, engine_weights({"individual_priority": 100, "fairness": 0}))
    assert [a.employee_id for a in r.assignments] == ["hi"]


def test_days_balance_and_sunday_balance_are_scored():
    sunday = date(2026, 12, 6)
    slots = [slot("s1", sunday, time(8), time(17)), slot("s2", date(2026, 12, 13), time(8), time(17))]
    emps = [Employee("a", "A", {"B": PRIORITY}), Employee("b", "B", {"B": PRIORITY})]
    r = run(slots, emps, engine_weights({"sunday_balance": 100, "fairness": 0}))
    assert {a.employee_id for a in r.assignments} == {"a", "b"}  # un dimanche chacun plutôt que deux pour le même
