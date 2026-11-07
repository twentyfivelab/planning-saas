"""Nouveaux paramètres de la fiche collaborateur : jours max, préférence horaire, quotas de dimanches, horaires autorisés."""
from datetime import date, time, timedelta


from planning_solver import solve
from planning_solver.demo_nov2026 import (SUNDAY_TOTAL, SUNDAYS, build_input)
from planning_solver.model import (BrandBudget, Employee, OutsideShift, PRIORITY, Slot, SolverConfig, SolverInput,
                                   slot_category, site_start_times, time_category)
from planning_solver.sundays import sunday_summary
from planning_solver.validator import validate

NOV = (date(2026, 11, 1), date(2026, 11, 30))


def slot(sid, day, st, en, site="S", tag="day", brand="B", **kw):
    return Slot(sid, day, site, st, en, 60, {brand: (en.hour - st.hour - 1) * 60 + (en.minute - st.minute)}, tag=tag, **kw)


def emp(i, **kw):
    return Employee(i, i, {"B": PRIORITY}, **kw)


def run(slots, emps, period=NOV, budgets=None, **kw):
    cfg = SolverConfig(time_limit_s=10, workers=1, **kw.pop("cfg", {}))
    return solve(SolverInput(period[0], period[1], slots, emps, budgets or [BrandBudget("B", 10 ** 6)], cfg, **kw))


def day_slots(days, prefix="d", st=time(9), en=time(18)):
    return [slot(f"{prefix}{d.isoformat()}", d, st, en) for d in days]


def dates(start, n):
    return [start + timedelta(days=i) for i in range(n)]


# ---------- nombre maximum de jours ----------
def test_weekly_max_days_never_exceeded():
    week = dates(date(2026, 11, 2), 7)  # lundi -> dimanche
    res = run(day_slots(week), [emp("zaki", max_days_count=4, max_days_period="week")])
    assert len(res.assignments) == 4 and res.hard_violations == []
    assert len(res.uncovered_slots) == 3 and res.status == "partiellement_couvert"


def test_weekly_cap_applies_to_each_week_independently():
    days = dates(date(2026, 11, 2), 14)
    res = run(day_slots(days), [emp("zaki", max_days_count=4, max_days_period="week")])
    assert len(res.assignments) == 8 and res.hard_violations == []


def test_monthly_max_days_never_exceeded():
    days = dates(date(2026, 11, 2), 25)
    res = run(day_slots(days), [emp("sahra", max_days_count=20, max_days_period="month")], cfg={"max_consecutive_days": 31})
    assert len(res.assignments) == 20 and res.hard_violations == []
    assert any(i.code == "NO_CANDIDATE" or i.code == "COMBINED_CONSTRAINTS" for i in res.diagnostics)


def test_no_restriction_when_no_preference():
    days = dates(date(2026, 11, 2), 6)
    res = run(day_slots(days), [emp("x", max_days_count=None, max_days_period=None)])
    assert len(res.assignments) == 6


def test_weekly_limit_counts_days_of_neighbour_period_for_straddling_weeks():
    # semaine du lun. 26 oct. au dim. 1er nov. : 4 jours déjà travaillés en octobre, plafond 4 -> le 1er nov. est interdit
    out_days = [OutsideShift("zaki", date(2026, 10, 26) + timedelta(days=i), time(9), time(18)) for i in range(4)]
    s = [slot("nov1", date(2026, 11, 1), time(9), time(18))]
    zaki = lambda: emp("zaki", max_days_count=4, max_days_period="week")  # noqa: E731
    blocked = run(s, [zaki()], outside_shifts=out_days)
    assert blocked.assignments == [] and blocked.uncovered_slots == ["nov1"]
    assert run(s, [zaki()], outside_shifts=out_days[:3]).assignments  # 3 + 1 = 4 : autorisé
    # sans historique voisin : seuls les jours de la période comptent, et le manque est signalé
    res = run(s, [zaki()])
    assert res.assignments and any(i.code == "WEEK_BOUNDARY_HISTORY_MISSING" for i in res.missing_data)


def test_weekly_limit_on_the_december_side_of_the_boundary():
    out_days = [OutsideShift("zaki", date(2026, 12, 1) + timedelta(days=i), time(9), time(18)) for i in range(4)]
    s = [slot("nov30", date(2026, 11, 30), time(9), time(18))]
    res = run(s, [emp("zaki", max_days_count=4, max_days_period="week")], outside_shifts=out_days)
    assert res.assignments == []  # 4 jours en décembre, même semaine ISO que le 30 nov.


def test_validator_flags_violation_of_weekly_cap_on_straddling_week():
    from planning_solver.model import Assignment
    out_days = [OutsideShift("zaki", date(2026, 10, 26) + timedelta(days=i), time(9), time(18)) for i in range(4)]
    s = [slot("nov1", date(2026, 11, 1), time(9), time(18))]
    inp = SolverInput(*NOV, s, [emp("zaki", max_days_count=4, max_days_period="week")], [], SolverConfig(), outside_shifts=out_days)
    a = Assignment("nov1", "zaki", date(2026, 11, 1), time(9), time(18), 540, 60, 480, {"B": 480})
    assert any(v.startswith("MAX_DAYS_WEEK") for v in validate(inp, [a]))


def test_rest_and_consecutive_days_across_the_period_boundary():
    # shift de fermeture le 31 oct. (jusqu'à 21 h) : une ouverture à 6 h le 1er nov. violerait le repos de 11 h
    out = [OutsideShift("x", date(2026, 10, 31), time(12), time(21))]
    s = [slot("open", date(2026, 11, 1), time(6), time(15))]
    assert run(s, [emp("x")], outside_shifts=out).assignments == []
    assert run(s, [emp("x")]).assignments
    # 6 jours consécutifs déjà travaillés avant la période : le 1er jour est interdit
    out6 = [OutsideShift("x", date(2026, 11, 1) - timedelta(days=k), time(9), time(18)) for k in range(1, 7)]
    assert run([slot("d1", date(2026, 11, 1), time(9), time(18))], [emp("x")], outside_shifts=out6).assignments == []


# ---------- préférence horaire ----------
def two_time_site():
    d = date(2026, 11, 3)
    return [slot("matin", d, time(6), time(15), site="S2", tag="open"), slot("soir", d, time(12), time(21), site="S2", tag="close")]


def test_time_categories_follow_start_time_and_single_schedule_sites_are_neutral():
    assert [time_category(time(h)) for h in (6, 7, 8)] == ["matin"] * 3
    assert [time_category(time(h)) for h in (9, 10, 11)] == ["middle"] * 3
    assert time_category(time(12)) == "soir" and time_category(time(12, 30)) == "soir"
    inp = SolverInput(*NOV, [slot("a", date(2026, 11, 3), time(9), time(18), site="CAILLER")] + two_time_site(), [], [])
    starts = site_start_times(inp)
    assert slot_category(inp.slots[0], starts) is None  # un seul horaire : neutre
    assert slot_category(inp.slots[1], starts) == "matin" and slot_category(inp.slots[2], starts) == "soir"


def test_strict_time_preference_is_a_hard_constraint():
    s = two_time_site()
    soir = emp("e", time_pref="soir", time_pref_strict=True)
    res = run(s, [soir])
    assert [a.slot_id for a in res.assignments] == ["soir"] and res.uncovered_slots == ["matin"]
    issue = next(i for i in res.diagnostics if i.code == "NO_CANDIDATE")
    assert "préférence horaire stricte" in issue.constraints
    assert res.hard_violations == []


def test_strict_preference_does_not_block_single_schedule_sites():
    s = [slot("c", date(2026, 11, 3), time(9), time(18), site="CAILLER")]
    assert run(s, [emp("e", time_pref="soir", time_pref_strict=True)]).assignments


def test_soft_time_preference_steers_assignment_but_never_blocks_coverage():
    s = two_time_site()
    a, b = emp("a", time_pref="matin"), emp("b", time_pref="soir")
    res = run(s, [a, b])
    assert {x.slot_id: x.employee_id for x in res.assignments} == {"matin": "a", "soir": "b"}
    # un seul collaborateur « matin » (souple) : il couvre aussi le soir plutôt que de laisser un trou
    solo = run(s, [emp("a", time_pref="matin")], cfg={"rest_hours": 0})
    assert len(solo.assignments) >= 1 and res.hard_violations == []


def test_strict_never_sacrificed_for_soft_preference_validator_agrees():
    from planning_solver.model import Assignment
    s = two_time_site()
    inp = SolverInput(*NOV, s, [emp("e", time_pref="soir", time_pref_strict=True)], [])
    bad = Assignment("matin", "e", date(2026, 11, 3), time(6), time(15), 540, 60, 480, {"B": 480})
    assert any(v.startswith("TIME_PREF_STRICT") for v in validate(inp, [bad]))


# ---------- quotas de dimanches ----------
def sunday_slots(n=5, per_day=1):
    return [slot(f"s{d.isoformat()}{k}", d, time(6 + k, 0), time(15 + k, 0), tag="open") for d in SUNDAYS[:n] for k in range(per_day)]


def test_sunday_quota_max_is_a_hard_cap():
    res = run(sunday_slots(), [emp("mila", sunday_quota=2, sunday_mode="max")])
    assert len(res.assignments) == 2 and res.hard_violations == []


def test_sunday_quota_zero_forbids_sundays():
    res = run(sunday_slots(), [emp("x", sunday_quota=0)])
    assert res.assignments == []
    assert any("quota de 0 dimanche" in c for i in res.diagnostics for c in i.constraints)


def test_sunday_quota_exact_is_pursued_without_exceeding():
    res = run(sunday_slots(), [emp("a", sunday_quota=3, sunday_mode="exact"), emp("b", sunday_quota=0)])
    assert len([x for x in res.assignments if x.employee_id == "a"]) == 3
    cfg = {"max_consecutive_days": 6}
    over = run(sunday_slots(), [emp("a", sunday_quota=3, sunday_mode="exact")], cfg=cfg)
    assert len(over.assignments) == 3  # jamais plus que le quota, même s'il reste des shifts


def test_no_two_sunday_shifts_for_same_person_the_same_day():
    res = run(sunday_slots(n=2, per_day=2), [emp("a", sunday_quota=5), emp("b", sunday_quota=5)], cfg={"rest_hours": 0})
    per = {}
    for a in res.assignments:
        per.setdefault((a.employee_id, a.day), 0)
        per[a.employee_id, a.day] += 1
    assert per and all(n == 1 for n in per.values()) and len(res.assignments) == 4


def test_sunday_quota_respects_availability_and_reports_warning():
    e = emp("a", sunday_quota=3, sunday_mode="exact", unavailable_dates={SUNDAYS[0], SUNDAYS[1], SUNDAYS[2]})
    inp = SolverInput(*NOV, sunday_slots(), [e], [])
    info = sunday_summary(inp)["employees"]["a"]
    assert info["available_sundays"] == 2 and any("Seulement 2" in w for w in info["warnings"])
    assert len(run(sunday_slots(), [e]).assignments) == 2


def test_november_2026_sunday_total_is_35_not_40():
    inp = build_input()
    sm = sunday_summary(inp)
    assert [d.isoformat() for d in SUNDAYS] == sm["sundays"] == ["2026-11-01", "2026-11-08", "2026-11-15", "2026-11-22", "2026-11-29"]
    assert sm["per_sunday"] == 7 and sm["total"] == SUNDAY_TOTAL == 35
    assert sm["by_site"] == {"GVA3": 15, "Pilar": 10, "GVA9": 10}
    # chaque dimanche : GVA3 06-15 / 10-19 / 12-21, Pilar 06-15 / 11-20, GVA9 07-16 / 12h30-21h30
    day = [s for s in inp.slots if s.day == SUNDAYS[0]]
    assert sorted((s.site, f"{s.start:%H:%M}", f"{s.end:%H:%M}") for s in day) == sorted([
        ("GVA3", "06:00", "15:00"), ("GVA3", "10:00", "19:00"), ("GVA3", "12:00", "21:00"),
        ("Pilar", "06:00", "15:00"), ("Pilar", "11:00", "20:00"), ("GVA9", "07:00", "16:00"), ("GVA9", "12:30", "21:30")])
    # Ploom seul : aucune autre marque le dimanche
    assert {b for s in inp.slots if s.day.weekday() == 6 for b in s.brands} <= {"Ploom GVA3", "Ploom Pilar", "Ploom GVA9"}
    assert all(s.effective_minutes == 480 for s in day)


def test_sunday_counter_reserved_versus_planned_without_double_counting():
    inp = build_input()
    emps = {e.id: e for e in inp.employees}
    assert sunday_summary(inp)["remaining_to_reserve"] == 35 and sunday_summary(inp)["reserved"] == 0
    emps["mila"].sunday_quota, emps["mila"].sunday_mode = 2, "exact"
    assert sunday_summary(inp)["remaining_to_reserve"] == 33  # 35 - 2
    emps["abdu"].sunday_quota, emps["abdu"].sunday_mode = 3, "exact"
    sm = sunday_summary(inp)
    assert (sm["reserved"], sm["remaining_to_reserve"]) == (5, 30)
    # un quota « maximum » est aussi un dimanche attribué : il réduit le restant ; le détail garde la part garantie / plafonnée
    emps["sabrina"].sunday_quota, emps["sabrina"].sunday_mode = 4, "max"
    sm = sunday_summary(inp)
    assert (sm["reserved"], sm["reserved_exact"], sm["reserved_max"], sm["remaining_to_reserve"]) == (9, 5, 4, 26)
    assert sm["planned"] == 0 and sm["unplanned"] == 35  # rien de planifié : réservé != réalisé
    # modifier un quota met le compteur à jour immédiatement (recalcul à partir des quotas courants)
    emps["mila"].sunday_quota = 1
    assert sunday_summary(inp)["remaining_to_reserve"] == 27
    emps["mila"].sunday_quota = None
    assert sunday_summary(inp)["remaining_to_reserve"] == 28


def test_sunday_alert_when_quotas_cannot_cover_all_shifts():
    inp = build_input()
    for e in inp.employees:
        e.sunday_quota, e.sunday_mode = 1, "exact"  # 17 collaborateurs x 1 = 17 < 35, plus personne de flexible
    sm = sunday_summary(inp)
    assert sm["reserved"] == len(inp.employees) and sm["flexible_employees"] == 0
    warn = [a for a in sm["alerts"] if a["level"] == "warning"]
    assert warn and f"{35 - len(inp.employees)} shift(s) du dimanche ne peuvent être couverts" in warn[0]["text"]


def test_demo_with_sunday_quotas_respects_them_and_reports_real_counts():
    inp = build_input(config=SolverConfig(time_limit_s=40))
    emps = {e.id: e for e in inp.employees}
    emps["mila"].sunday_quota, emps["mila"].sunday_mode = 2, "exact"
    emps["abdu"].sunday_quota, emps["abdu"].sunday_mode = 3, "exact"
    emps["zaki"].sunday_quota, emps["zaki"].sunday_mode = 0, "max"
    emps["sahra"].max_days_count, emps["sahra"].max_days_period = 20, "month"
    emps["zaki"].max_days_count, emps["zaki"].max_days_period = 4, "week"
    res = solve(inp)
    assert res.hard_violations == [] and validate(inp, res.assignments) == []
    sundays = {e: sum(1 for a in res.assignments if a.employee_id == e and a.day.weekday() == 6) for e in emps}
    assert sundays["zaki"] == 0 and sundays["mila"] <= 2 and sundays["abdu"] <= 3
    assert res.sunday["total"] == 35 and res.sunday["planned"] + res.sunday["unplanned"] == 35
    assert sum(1 for a in res.assignments if a.employee_id == "sahra") <= 20
    zaki_days = {}
    for a in res.assignments:
        if a.employee_id == "zaki":
            zaki_days.setdefault(a.day.isocalendar()[:2], set()).add(a.day)
    assert all(len(v) <= 4 for v in zaki_days.values())


# ---------- horaires autorisés et budgets stricts ----------
def test_validator_rejects_hours_outside_allowed_schedules():
    from planning_solver.model import Assignment
    s = [slot("odd", date(2026, 11, 3), time(8), time(17), site="Cartier"), slot("ok", date(2026, 11, 4), time(9), time(18), site="Cailler")]
    inp = SolverInput(*NOV, s, [emp("x")], [], allowed_times={"Cartier": [(time(8), time(17))], "Cailler": [(time(10), time(19))]})
    a1 = Assignment("odd", "x", date(2026, 11, 3), time(8), time(17), 540, 60, 480, {"B": 480})
    a2 = Assignment("ok", "x", date(2026, 11, 4), time(9), time(18), 540, 60, 480, {"B": 480})
    v = validate(inp, [a1, a2])
    assert any("SCHEDULE_NOT_ALLOWED: ok" in x for x in v) and not any("SCHEDULE_NOT_ALLOWED: odd" in x for x in v)


def test_all_demo_slots_use_only_authorised_schedules():
    inp = build_input()
    for s in inp.slots:
        assert (s.start, s.end) in inp.allowed_times[s.site], s.id
    assert all(s.break_minutes == 60 and s.effective_minutes == 480 for s in inp.slots)


def test_strict_budget_never_exceeded_non_strict_may_be_exceeded_with_penalty():
    d = dates(date(2026, 11, 2), 3)
    s = day_slots(d)
    strict = run(s, [emp("x")], budgets=[BrandBudget("B", 16 * 60, strict=True)])
    assert sum(a.effective_minutes for a in strict.assignments) <= 16 * 60 and strict.hard_violations == []
    soft = run(s, [emp("x")], budgets=[BrandBudget("B", 16 * 60, strict=False)])
    assert sum(a.effective_minutes for a in soft.assignments) == 24 * 60 and soft.hard_violations == []
    assert "budget_over" in soft.objective and soft.objective["budget_over"] > 0


def test_every_generated_plan_is_checked_by_the_independent_validator():
    inp = build_input(config=SolverConfig(time_limit_s=40))
    res = solve(inp)
    assert validate(inp, res.assignments) == res.hard_violations == []


# ---------- indisponibilités datées et marques autorisées ----------
def test_blocked_dates_are_never_assigned_even_when_nobody_else_can_cover():
    blocked = {date(2026, 11, 5), date(2026, 11, 12), date(2026, 11, 18)}
    days = [date(2026, 11, d) for d in (4, 5, 11, 12, 17, 18)]
    res = run(day_slots(days), [emp("zaki", unavailable_dates=blocked)])
    assert {a.day for a in res.assignments} == set(days) - blocked
    assert sorted(res.uncovered_slots) == sorted(f"d{d.isoformat()}" for d in blocked)
    assert any(i.code == "NO_CANDIDATE" and "indisponible / absent" in i.constraints for i in res.diagnostics)
    assert res.hard_violations == []


def test_blocked_date_is_flagged_by_validator_on_an_existing_plan():
    from planning_solver.model import Assignment
    d = date(2026, 11, 5)
    inp = SolverInput(*NOV, day_slots([d]), [emp("zaki", unavailable_dates={d})], [])
    a = Assignment(f"d{d.isoformat()}", "zaki", d, time(9), time(18), 540, 60, 480, {"B": 480})
    v = validate(inp, [a])
    assert v and v[0].startswith("UNAVAILABLE: zaki") and f"d{d.isoformat()}" in v[0]


def test_unselected_brand_is_never_assigned_and_levels_order_priority_secondary_reinforce():
    from planning_solver.model import REINFORCE, SECONDARY
    d = date(2026, 11, 3)
    s = [slot("a", d, time(9), time(18), brand="X")]
    p, sec, rf = (Employee(n, n, {"X": lv}) for n, lv in (("p", PRIORITY), ("s", SECONDARY), ("r", REINFORCE)))
    other = Employee("o", "o", {"Y": PRIORITY})  # marque X non sélectionnée
    b = [BrandBudget("X", 10 ** 6)]
    assert run(s, [other], budgets=b).assignments == []
    assert [a.employee_id for a in run(s, [rf, sec, p, other], budgets=b).assignments] == ["p"]
    assert [a.employee_id for a in run(s, [rf, sec, other], budgets=b).assignments] == ["s"]
    assert [a.employee_id for a in run(s, [rf, other], budgets=b).assignments] == ["r"]
    issue = run(s, [other], budgets=b).diagnostics[0]
    assert issue.code == "NO_CANDIDATE" and "marque non éligible" in issue.constraints
