"""Tuteur et binôme (19/11/2026) : un simple chevauchement d'horaires n'est PAS une présence pendant toute la période qui nécessite un
accompagnement. Portées : même jour (historique), chevauchement simple, couverture complète (un ou plusieurs tuteurs qui se relaient).
Moteur, vérificateur indépendant et évaluateur appliquent la même règle. Données fictives."""
from datetime import date, time, timedelta

from planning_solver import solve
from planning_solver.context import presence_ok
from planning_solver.model import PRIORITY, Employee, Relation, Slot, SolverConfig, SolverInput
from planning_solver.objective import evaluate
from planning_solver.validator import violations

D = date(2026, 11, 2)
DAYS = [D + timedelta(days=k) for k in range(7)]


def sl(sid, d, h0, h1, site="S", mandatory=True, brand="A"):
    tmp = Slot(sid, d, site, time(h0), time(h1), 0, {brand: 0}, mandatory=mandatory)
    return Slot(sid, d, site, time(h0), time(h1), 0, {brand: tmp.effective_minutes}, mandatory=mandatory)


def emp(eid, brand="A", **kw):
    return Employee(eid, eid.capitalize(), {brand: PRIORITY}, **kw)


def test_chevauchement_simple_n_est_pas_une_couverture_complete():
    nouveau = sl("n", D, 9, 18)
    matin, apres_midi = sl("t1", D, 8, 13), sl("t2", D, 13, 19)
    assert presence_ok(nouveau, [matin], "overlap") and not presence_ok(nouveau, [matin], "full")  # 13:00-18:00 sans tuteur
    assert presence_ok(nouveau, [matin, apres_midi], "full")  # deux tuteurs qui se relaient sans trou
    assert not presence_ok(nouveau, [sl("t3", D, 8, 12), apres_midi], "full")  # trou de 12:00 à 13:00
    assert not presence_ok(nouveau, [sl("t4", D, 9, 18, site="X")], "full")  # autre site : ne compte pas


def _inp(scope, tutor_slots):
    nouveau = [sl("n", D, 9, 18)]
    e_new = emp("nouveau", relations=[Relation("mentor", "tuteur", True, scope)])
    # le tuteur tient une autre marque (B) sur le même site : il ne peut pas prendre lui-même le shift du nouveau
    return SolverInput(DAYS[0], DAYS[-1], nouveau + tutor_slots, [e_new, emp("tuteur", brand="B")], [], config=SolverConfig(time_limit_s=10, workers=4))


def test_moteur_couverture_complete_stricte():
    """Seul shift possible du tuteur : 12:00-18:00. Avec « chevauchement », le nouveau peut travailler ; avec « couverture complète »,
    jamais (il serait seul de 9:00 à 12:00) : le shift reste non couvert plutôt que de le laisser seul."""
    tutor = [sl("t", D, 12, 18, brand="B")]
    r1 = solve(_inp("overlap", tutor))
    assert {(a.employee_id, a.slot_id) for a in r1.assignments} >= {("nouveau", "n"), ("tuteur", "t")}
    r2 = solve(_inp("full", tutor))
    assert ("nouveau", "n") not in {(a.employee_id, a.slot_id) for a in r2.assignments}
    # avec un tuteur couvrant toute la plage (8:00-18:00), le nouveau travaille
    r3 = solve(_inp("full", [sl("t", D, 8, 18, brand="B")]))
    assert ("nouveau", "n") in {(a.employee_id, a.slot_id) for a in r3.assignments}


def test_verificateur_et_evaluateur_identiques_au_moteur():
    from planning_solver.model import Assignment
    inp = _inp("full", [sl("t", D, 12, 18, brand="B")])
    s = {x.id: x for x in inp.slots}

    def asg(eid, sid):
        h = s[sid].hours
        return Assignment(sid, eid, s[sid].day, s[sid].start, s[sid].end, h.presence_minutes, h.break_minutes, h.effective_minutes, dict(s[sid].allocations))
    plan = [asg("nouveau", "n"), asg("tuteur", "t")]
    assert any("MENTOR_MISSING" in str(v) and "toute la plage" in str(v) for v in violations(inp, plan))
    inp_ok = _inp("overlap", [sl("t", D, 12, 18, brand="B")])
    assert not any("MENTOR_MISSING" in str(v) for v in violations(inp_ok, plan))
    # binôme souple (préférence) : coût du moteur = coût recalculé
    e1 = emp("a", relations=[Relation("work_together", "b", False, "full")])
    inp2 = SolverInput(DAYS[0], DAYS[-1], [sl("x", D, 9, 18), sl("y", D, 9, 13, mandatory=False), sl("z", D + timedelta(days=1), 9, 18)],
                       [e1, emp("b")], [], config=SolverConfig(time_limit_s=10, workers=4, hierarchical=False))
    res = solve(inp2)
    assert evaluate(inp2, res.assignments).get("family", 0) == res.objective.get("family", 0)
