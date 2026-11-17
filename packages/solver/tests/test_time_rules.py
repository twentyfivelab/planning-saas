"""Décompte du temps : minutes entières, passage de minuit, changements d'heure (Europe/Zurich), chevauchements entre sites,
frontière entre deux mois, co-branding sans double comptage, jour travaillé compté une seule fois.

Règle de rattachement (documentée dans docs/suivi-wfm.md) : un shift appartient au JOUR et au MOIS de son début."""
from datetime import date, time, timedelta

from planning_solver.model import Assignment, Employee, PRIORITY, Slot, SolverConfig, SolverInput
from planning_solver.timecalc import shift_bounds, shift_hours, split_allocation
from planning_solver.validator import violations


def test_shift_de_nuit_passe_minuit():
    h = shift_hours(date(2026, 11, 10), time(22, 0), time(6, 0), 30)
    assert (h.presence_minutes, h.break_minutes, h.effective_minutes) == (480, 30, 450)
    s, e = shift_bounds(date(2026, 11, 10), time(22, 0), time(6, 0))
    assert e.date() == date(2026, 11, 11)


def test_nuits_de_changement_d_heure():
    # 25 octobre 2026 : 3 h -> 2 h (une heure de plus) ; 29 mars 2026 : 2 h -> 3 h (une heure de moins)
    assert shift_hours(date(2026, 10, 24), time(22, 0), time(6, 0), 0).presence_minutes == 9 * 60
    assert shift_hours(date(2026, 3, 28), time(22, 0), time(6, 0), 0).presence_minutes == 7 * 60
    assert shift_hours(date(2026, 10, 25), time(9, 0), time(18, 0), 60).effective_minutes == 8 * 60  # journée normale le jour même


def test_co_branding_huit_heures_pour_le_collaborateur_quatre_par_marque():
    h = shift_hours(date(2026, 11, 10), time(9, 0), time(18, 0), 60)
    parts = split_allocation(h.effective_minutes, {"Nuxe": 0.5, "Cellcosmet": 0.5})
    assert h.effective_minutes == 480 and parts == {"Nuxe": 240, "Cellcosmet": 240}
    assert sum(split_allocation(481, {"A": 1, "B": 1, "C": 1}).values()) == 481  # arrondis : jamais une minute perdue ni ajoutée


def _slot(sid, d, site, start, end, brk, alloc):
    h = shift_hours(d, start, end, brk)
    return Slot(sid, d, site, start, end, brk, {b: h.effective_minutes * v // sum(alloc.values()) for b, v in alloc.items()})


def _assign(s, eid):
    h = s.hours
    return Assignment(s.id, eid, s.day, s.start, s.end, h.presence_minutes, h.break_minutes, h.effective_minutes, dict(s.allocations))


def test_chevauchement_detecte_entre_deux_sites_et_deux_marques():
    d = date(2026, 11, 10)
    a = _slot("A", d, "S1", time(9), time(15), 0, {"Nuxe": 1})
    b = _slot("B", d, "S2", time(14), time(20), 0, {"Cartier": 1})
    emp = Employee("ana", "Ana", {"Nuxe": PRIORITY, "Cartier": PRIORITY})
    inp = SolverInput(d, d, [a, b], [emp], [], SolverConfig(rest_hours=0))
    assert any(v.code == "OVERLAP" for v in violations(inp, [_assign(a, "ana"), _assign(b, "ana")]))


def test_shift_de_nuit_rattache_au_mois_de_son_debut():
    """31 octobre 22 h -> 1er novembre 6 h : compté en octobre (jour et heures), jamais deux fois."""
    oct31 = date(2026, 10, 31)
    night = _slot("N", oct31, "S1", time(22), time(6), 0, {"A": 1})
    days = [date(2026, 10, 9) + timedelta(days=k) for k in range(22)]  # 22 shifts de 8 h déjà en octobre = 176 h
    day_slots = [_slot(f"D{k}", dd, "S1", time(9), time(18), 60, {"A": 1}) for k, dd in enumerate(days)]
    emp = Employee("ana", "Ana", {"A": PRIORITY})
    inp = SolverInput(date(2026, 10, 1), date(2026, 11, 30), day_slots + [night], [emp], [],
                      SolverConfig(monthly_cap_minutes=176 * 60, max_consecutive_days=40))
    found = violations(inp, [_assign(s, "ana") for s in day_slots] + [_assign(night, "ana")])
    cap = [v for v in found if v.code == "MONTHLY_CAP"]
    assert len(cap) == 1 and "octobre 2026" in cap[0].text and cap[0].reached == "184 h"  # 176 h + 8 h de nuit, en octobre


def test_un_jour_avec_deux_affectations_compte_une_fois():
    d = date(2026, 11, 10)
    am = _slot("AM", d, "S1", time(6), time(10), 0, {"A": 1})
    pm = _slot("PM", d, "S2", time(11), time(15), 0, {"A": 1})
    emp = Employee("ana", "Ana", {"A": PRIORITY}, max_days_month=1)
    inp = SolverInput(date(2026, 11, 1), date(2026, 11, 30), [am, pm], [emp], [], SolverConfig(rest_hours=0))
    assert not [v for v in violations(inp, [_assign(am, "ana"), _assign(pm, "ana")]) if v.code == "MAX_DAYS_MONTH"]


def test_regles_du_verificateur_reecrites_et_equivalentes_au_generateur():
    """Le vérificateur ne réutilise plus le code du générateur : ses propres fonctions donnent les mêmes résultats sur 2 000 cas."""
    import random
    from planning_solver.context import required_break
    from planning_solver.model import site_start_times, slot_category
    from planning_solver.validator import _break_needed, _category, _starts_by_site
    rnd = random.Random(3)
    for _ in range(2000):
        rules = [(rnd.choice([300, 330, 420, 540]), rnd.choice([15, 30, 60])) for _k in range(rnd.randint(0, 3))]
        h0, m0 = rnd.randint(5, 14), rnd.choice([0, 15, 30, 45])
        d = date(2026, 11, rnd.randint(1, 30))
        s = _slot("S", d, rnd.choice(["A", "B"]), time(h0, m0), time(min(23, h0 + rnd.randint(3, 9)), m0), rnd.choice([0, 30, 60]), {"X": 1})
        assert _break_needed(rules, s.effective_minutes) == required_break(rules, s)
        others = [_slot(f"O{k}", d, s.site, time(rnd.randint(5, 14), 0), time(20, 0), 0, {"X": 1}) for k in range(rnd.randint(0, 2))]
        inp = SolverInput(d, d, [s, *others], [], [], SolverConfig())
        assert _category(s, _starts_by_site(inp)) == slot_category(s, site_start_times(inp))
