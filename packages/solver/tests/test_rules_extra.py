"""Absences partielles, horaires obligatoires par collaborateur, temps de déplacement entre sites ; sérialisation du contexte figé."""
from datetime import date, time, timedelta

from planning_solver import solve
from planning_solver.model import Assignment, Employee, PRIORITY, Relation, Slot, SolverConfig, SolverInput
from planning_solver.serialize import input_from_dict, input_to_dict
from planning_solver.validator import violations

D = [date(2026, 11, 2) + timedelta(days=k) for k in range(5)]


def slot(sid, d, start, end, site="S1", brk=0):
    tmp = Slot(sid, d, site, time(*start), time(*end), brk, {"A": 0})
    return Slot(sid, d, site, time(*start), time(*end), brk, {"A": tmp.effective_minutes})


def emp(eid, **kw):
    return Employee(eid, eid.capitalize(), {"A": PRIORITY}, **kw)


def assign(s, eid):
    h = s.hours
    return Assignment(s.id, eid, s.day, s.start, s.end, h.presence_minutes, h.break_minutes, h.effective_minutes, dict(s.allocations))


def cfg(**kw):
    kw.setdefault("time_limit_s", 10)
    kw.setdefault("workers", 4)
    return SolverConfig(**kw)


def test_absence_partielle_bloque_seulement_les_shifts_qui_la_chevauchent():
    d = D[0]
    morning, evening = slot("M", d, (8, 0), (12, 0)), slot("E", d, (15, 0), (19, 0))
    ana = emp("ana", unavailable_windows={(d, time(7, 0), time(13, 0))})  # rendez-vous le matin
    inp = SolverInput(D[0], D[-1], [morning, evening], [ana], [], cfg())
    res = solve(inp)
    assert [a.slot_id for a in res.assignments] == ["E"] and res.uncovered_slots == ["M"]  # l'après-midi reste possible
    v = [x for x in violations(inp, [assign(morning, "ana")]) if x.code == "UNAVAILABLE_PARTIAL"]
    assert len(v) == 1 and "07:00" in v[0].text and "13:00" in v[0].text
    assert not [x for x in violations(inp, [assign(evening, "ana")]) if x.code == "UNAVAILABLE_PARTIAL"]


def test_horaires_obligatoires_du_collaborateur():
    s_ok, s_late, s_night = slot("OK", D[0], (9, 0), (17, 0)), slot("LATE", D[1], (12, 0), (21, 0)), slot("N", D[2], (22, 0), (6, 0))
    ana = emp("ana", work_window=(time(8, 0), time(18, 0)))
    inp = SolverInput(D[0], D[-1], [s_ok, s_late, s_night], [ana], [], cfg())
    res = solve(inp)
    assert [a.slot_id for a in res.assignments] == ["OK"] and sorted(res.uncovered_slots) == ["LATE", "N"]
    codes = [x.code for x in violations(inp, [assign(s_late, "ana"), assign(s_night, "ana")]) if x.code == "WORK_WINDOW"]
    assert codes == ["WORK_WINDOW", "WORK_WINDOW"]


def test_temps_de_deplacement_entre_sites():
    d = D[0]
    a, b = slot("A", d, (8, 0), (12, 0), site="S1"), slot("B", d, (12, 30), (16, 0), site="S2")
    ana = emp("ana")
    base = dict(config=cfg(rest_hours=0))
    # sans temps de déplacement déclaré : les deux shifts s'enchaînent
    res = solve(SolverInput(D[0], D[-1], [a, b], [ana], [], **base))
    assert sorted(x.slot_id for x in res.assignments) == ["A", "B"]
    # 45 min entre S1 et S2 (déclaré dans un seul sens, valable dans les deux) : 30 min ne suffisent pas
    inp = SolverInput(D[0], D[-1], [a, b], [ana], [], travel_minutes={("S2", "S1"): 45}, **base)
    res = solve(inp)
    assert len(res.assignments) == 1 and not res.hard_violations
    v = [x for x in violations(inp, [assign(a, "ana"), assign(b, "ana")]) if x.code == "TRAVEL_TIME"]
    assert len(v) == 1 and v[0].limit == "45 min" and v[0].reached == "30 min"


def test_serialisation_aller_retour_des_nouvelles_regles():
    d = D[0]
    ana = emp("ana", unavailable_windows={(d, time(7, 0), time(13, 0))}, work_window=(time(8, 0), time(18, 0)),
              relations=[Relation("avoid_together", "ben", True, "overlap")])
    inp = SolverInput(D[0], D[-1], [slot("M", d, (8, 0), (12, 0))], [ana, emp("ben")], [], cfg(), travel_minutes={("S1", "S2"): 30})
    back = input_from_dict(input_to_dict(inp))
    e = back.employees[0]
    assert e.unavailable_windows == ana.unavailable_windows and e.work_window == ana.work_window
    assert e.relations[0].scope == "overlap" and e.relations[0].strict
    assert back.travel_minutes == {("S1", "S2"): 30}
    assert input_to_dict(back) == input_to_dict(inp)
