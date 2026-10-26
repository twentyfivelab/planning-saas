from collections import defaultdict
from datetime import date, time, timedelta

import pytest

from planning_solver import solve
from planning_solver.model import (Contract, Employee, PRIORITY, BrandBudget, Slot, SolverConfig, SolverInput)
from planning_solver.demo_nov2026 import build_input
from planning_solver.validator import validate

NAMES = {}


@pytest.fixture(scope="module")
def demo():
    inp = build_input(config=SolverConfig(time_limit_s=60))
    return inp, solve(inp)


def by_name(inp, res, name):
    eid = next(e.id for e in inp.employees if e.name == name)
    return [a for a in res.assignments if a.employee_id == eid]


def test_demo_hard_constraints_clean(demo):
    inp, res = demo
    assert res.hard_violations == []
    assert validate(inp, res.assignments) == []


def test_demo_is_partial_exploratory_and_not_validable(demo):
    _, res = demo
    assert res.status == "partiellement_couvert"
    assert res.mode == "simulation_exploratoire" and res.validable is False
    codes = {i.code for i in res.missing_data}
    assert {"CONTRACT_MISSING", "BRAND_REQUIREMENTS_MISSING", "LEGAL_REVIEW"} <= codes


def test_lindt_toblerone_isolated_128h(demo):
    _, res = demo
    rem = {b["brand"]: b["remaining_minutes"] for b in res.budgets if not b["requirements_defined"]}
    assert rem == {"Lindt": 3840, "Toblerone": 3840}
    assert sum(rem.values()) == 128 * 60


def test_budgets_reached_without_exceeding(demo):
    _, res = demo
    got = {b["brand"]: b["planned_minutes"] // 60 for b in res.budgets}
    assert got["Ploom GVA3"] == 720 and got["Ploom GVA9"] == 480 and got["Cartier"] == 64
    assert got["Valmont"] == 136 and got["Cellcosmet"] == 68 and got["Nuxe"] == 68 and got["Cailler"] == 88


def test_shift_counts(demo):
    _, res = demo
    n = defaultdict(int)
    for a in res.assignments:
        n[a.slot_id.split("|")[0]] += 1
    assert n["GVA3"] == 90 and n["GVA9"] == 60 and n["CARTIER"] == 8
    assert n["VALMONT"] == 17 and n["CN"] == 17 and n["CAILLER"] == 11


def test_cobranding_one_assignment_two_allocations(demo):
    _, res = demo
    cn = [a for a in res.assignments if a.slot_id.startswith("CN|")]
    assert all(a.allocations == {"Cellcosmet": 240, "Nuxe": 240} and a.effective_minutes == 480 for a in cn)


def test_sabrina_never_closes(demo):
    inp, res = demo
    slots = {s.id: s for s in inp.slots}
    assert all(slots[a.slot_id].tag != "close" for a in by_name(inp, res, "Sabrina"))


def test_jane_chloe_unavailability(demo):
    inp, res = demo
    assert all(a.day.weekday() != 1 for a in by_name(inp, res, "Jane"))
    assert all(a.day.weekday() not in (2, 5) for a in by_name(inp, res, "Chloé"))


def test_ying_max_three_days_per_week(demo):
    inp, res = demo
    wk = defaultdict(set)
    for a in by_name(inp, res, "Ying"):
        wk[a.day.isocalendar()[:2]].add(a.day)
    assert all(len(v) <= 3 for v in wk.values())


def test_zaki_rest_days_preference_reported(demo):
    inp, res = demo
    wk = defaultdict(set)
    for a in by_name(inp, res, "Zaki"):
        wk[a.day.isocalendar()[:2]].add(a.day)
    full = [w for w in wk if w in {(2026, 45), (2026, 46), (2026, 47), (2026, 48)}]
    assert all(len(wk[w]) <= 4 for w in full)  # >= 3 jours de repos (préférence forte respectée ici)


def test_weights_and_objective_exposed(demo):
    _, res = demo
    assert res.weights["coverage"] == 1000 and "fairness" in res.objective and res.duration_s > 0


# ---------- scénarios ciblés ----------

def mk_slot(sid, day, st, en, tag="day", brand="B", site="S", **kw):
    return Slot(sid, day, site, st, en, 60, {brand: (en.hour - st.hour - 1) * 60}, tag=tag, **kw)


def emp(i, **kw):
    return Employee(i, i, {"B": PRIORITY}, **kw)


def run(slots, emps, **kw):
    cfg = SolverConfig(time_limit_s=10, workers=1, **kw.pop("cfg", {}))
    return solve(SolverInput(date(2026, 11, 2), date(2026, 11, 30), slots, emps,
                             [BrandBudget("B", 10 ** 6)], cfg, **kw))


def test_no_double_assignment_overlapping_slots_two_sites():
    d = date(2026, 11, 3)
    s = [mk_slot("a", d, time(8), time(17), site="GVA3"), mk_slot("b", d, time(10), time(19), site="GVA9")]
    res = run(s, [emp("x")])
    assert len(res.assignments) == 1 and len(res.uncovered_slots) == 1
    assert len(run(s, [emp("x"), emp("y")]).assignments) == 2  # deux personnes : chacune une seule affectation


def test_eleven_hours_rest():
    d = date(2026, 11, 3)
    s = [mk_slot("close", d, time(12), time(21)), mk_slot("open", d + timedelta(days=1), time(6), time(15))]
    res = run(s, [emp("x")])
    assert len(res.assignments) == 1  # 9 h de repos < 11 h
    res2 = run(s, [emp("x"), emp("y")])
    assert len(res2.assignments) == 2 and res2.hard_violations == []


def test_rest_exactly_eleven_hours_is_allowed_and_threshold_is_configurable():
    d = date(2026, 11, 3)
    s = [mk_slot("close", d, time(12), time(21)), mk_slot("open", d + timedelta(days=1), time(8), time(17))]
    assert len(run(s, [emp("x")]).assignments) == 2  # 21:00 -> 08:00 = 11 h pile : autorisé
    s2 = [mk_slot("close", d, time(12), time(21)), mk_slot("open", d + timedelta(days=1), time(7), time(16))]
    assert len(run(s2, [emp("x")]).assignments) == 1  # 10 h : interdit
    assert len(run(s2, [emp("x")], cfg={"rest_hours": 9}).assignments) == 2  # seuil paramétrable


def test_max_consecutive_days_is_configurable():
    s = [mk_slot(f"d{i}", date(2026, 11, 2) + timedelta(days=i), time(9), time(18)) for i in range(5)]
    res = run(s, [emp("x")], cfg={"max_consecutive_days": 3})
    assert len(res.assignments) == 4 and res.hard_violations == []  # jours 0,1,2 puis repos puis 4
    assert len(run(s, [emp("x")]).assignments) == 5  # plafond par défaut (6) : tout est pourvu


def test_max_six_consecutive_days():
    s = [mk_slot(f"d{i}", date(2026, 11, 2) + timedelta(days=i), time(9), time(18)) for i in range(7)]
    res = run(s, [emp("x")])
    assert len(res.assignments) == 6 and len(res.uncovered_slots) == 1
    assert res.status == "partiellement_couvert"


def test_contract_cap_respected_only_when_provided():
    s = [mk_slot(f"d{i}", date(2026, 11, 2) + timedelta(days=i * 2), time(9), time(18)) for i in range(4)]
    res = run(s, [emp("x", contract=Contract(monthly_max_minutes=16 * 60))])
    assert sum(a.effective_minutes for a in res.assignments) == 16 * 60
    assert res.mode == "validable"
    assert run(s, [emp("x")]).mode == "simulation_exploratoire"


def test_infeasible_strict_gives_diagnostic_not_a_bad_plan():
    d = date(2026, 11, 3)
    s = [mk_slot("a", d, time(8), time(17)), mk_slot("b", d, time(9), time(18))]
    res = run(s, [emp("x")], cfg={"strict_coverage": True})
    assert res.status == "infaisable" and res.assignments == [] and not res.validable
    core = next(i for i in res.diagnostics if i.code == "INFEASIBLE_CORE")
    assert set(core.slots) == {"a", "b"} and core.suggestions


def test_no_candidate_diagnostic_names_cause():
    d = date(2026, 11, 3)
    res = run([mk_slot("a", d, time(8), time(17))], [emp("x", unavailable_dates={d})])
    issue = res.diagnostics[0]
    assert issue.code == "NO_CANDIDATE" and "indisponible / absent" in issue.constraints


def test_locked_assignment_kept_and_partial_reoptimization():
    d = date(2026, 11, 3)
    s = [mk_slot("a", d, time(8), time(17)), mk_slot("b", d + timedelta(days=1), time(8), time(17))]
    emps = [emp("x"), emp("y")]
    first = run(s, emps)
    prev = {a.slot_id: a.employee_id for a in first.assignments}
    other = "y" if prev["a"] == "x" else "x"
    res = run(s, emps, locked={"a": other}, previous=prev)
    assert {a.slot_id: a.employee_id for a in res.assignments}["a"] == other
    assert next(a for a in res.assignments if a.slot_id == "a").locked
    assert res.hard_violations == []


def test_lock_violating_hard_rule_is_infeasible_with_explanation():
    d = date(2026, 11, 3)
    res = run([mk_slot("a", d, time(8), time(17))], [emp("x", unavailable_dates={d})], locked={"a": "x"})
    assert res.status == "infaisable" and res.diagnostics


def test_preference_never_overrides_hard_rule():
    d = date(2026, 11, 3)
    x = emp("x", preferred_tags={"close"}, preference_strength=3, forbidden_tags={"close"})
    res = run([mk_slot("c", d, time(12), time(21), tag="close")], [x])
    assert res.assignments == []


def test_assumed_schedules_are_configurable_and_flagged_as_unvalidated_hypotheses():
    from datetime import time as t
    from planning_solver.demo_nov2026 import ASSUMED_CAILLER_TEMPLATE, HYPOTHETICAL_TEMPLATES, build_slots
    assert ASSUMED_CAILLER_TEMPLATE == (t(9), t(18)) and "CAILLER-09" in HYPOTHETICAL_TEMPLATES
    slots = build_slots(cn_templates=[(t(9), t(18))], cailler_template=(t(10), t(19)))
    assert {(x.start, x.end) for x in slots if x.id.startswith("CAILLER")} == {(t(10), t(19))}
    assert {x.start for x in slots if x.id.startswith("CN|")} == {t(9)}
    from planning_solver.demo_nov2026 import build_input
    from planning_solver.diagnostics import missing_data
    hyp = [i for i in missing_data(build_input()) if i.code == "HYPOTHESIS"]
    assert hyp and all(i.severity == "warning" and "NON VALIDÉE" in i.message for i in hyp)
    assert any("Cailler" in i.message for i in hyp) and any("Nuxe/Cellcosmet" in i.message for i in hyp)


def test_non_executed_legal_rules_are_declared_not_commercialisable():
    from planning_solver.demo_nov2026 import build_input
    from planning_solver.diagnostics import missing_data
    legal = next(i for i in missing_data(build_input()) if i.code == "LEGAL_REVIEW")
    assert legal.severity == "warning" and "Non commercialisable" in legal.message
    for rule in ("pauses légales", "travail de nuit", "travail du dimanche", "jeunes travailleurs"):
        assert rule in legal.message
