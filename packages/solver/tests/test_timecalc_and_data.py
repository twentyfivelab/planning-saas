from datetime import date, time

import pytest

from planning_solver.demo_nov2026 import BUDGET_HOURS, TOTAL_HOURS, build_slots, build_employees
from planning_solver.timecalc import shift_hours, split_allocation


def test_budget_total_1752():
    assert sum(BUDGET_HOURS.values()) == TOTAL_HOURS == 1752
    assert 720 + 480 + 64 + 136 + 68 + 68 + 88 + 64 + 64 == 1752


def test_presence_pause_effectif():
    h = shift_hours(date(2026, 11, 2), time(9), time(18), 60)
    assert (h.presence_hours, h.break_minutes, h.effective_hours) == (9, 60, 8)


def test_dst_change_is_reliable():
    # nuit du changement d'heure d'automne (25 oct. 2026) : 22:00 -> 06:00 = 9 h réelles
    h = shift_hours(date(2026, 10, 24), time(22), time(6), 0)
    assert h.presence_hours == 9


def test_cobranding_split_does_not_double_hours():
    assert split_allocation(480, {"Cellcosmet": 1, "Nuxe": 1}) == {"Cellcosmet": 240, "Nuxe": 240}
    assert sum(split_allocation(480, {"A": 3, "B": 1}).values()) == 480


@pytest.mark.parametrize("prefix,shifts,hours", [("GVA3", 90, 720), ("GVA9", 60, 480), ("CARTIER", 8, 64)])
def test_fixed_brands_shifts_and_hours(prefix, shifts, hours):
    s = [x for x in build_slots() if x.id.startswith(prefix + "|")]
    assert len(s) == shifts
    assert sum(x.effective_minutes for x in s) == hours * 60


def test_cartier_days():
    days = sorted(x.day.day for x in build_slots() if x.id.startswith("CARTIER"))
    assert days == [6, 7, 13, 14, 20, 21, 27, 28]


def test_no_contract_invented():
    assert all(e.contract is None for e in build_employees())


def test_no_lindt_toblerone_slots():
    assert not [s for s in build_slots() if {"Lindt", "Toblerone"} & set(s.brands)]
