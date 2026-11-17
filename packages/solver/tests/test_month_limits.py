"""Plafond mensuel d'heures de l'entreprise, jours minimum / maximum par mois, collaborateur supprimé, vérificateur structuré,
détail des incompatibilités et suivi du calcul."""
from datetime import date, time, timedelta

from planning_solver import solve
from planning_solver.compat import compatibility
from planning_solver.model import Assignment, Employee, OutsideShift, PRIORITY, Slot, SolverConfig, SolverInput
from planning_solver.validator import validate, violations

NOV = [date(2026, 11, 1) + timedelta(days=k) for k in range(30)]
CAP = 176 * 60


def slot(sid, d, site="S", brand="A", start=(9, 0), end=(18, 0), brk=60, **kw):
    """9 h – 18 h avec 1 h de pause = 8 h de travail effectif."""
    s0, s1 = time(*start), time(*end)
    tmp = Slot(sid, d, site, s0, s1, brk, {brand: 0})
    return Slot(sid, d, site, s0, s1, brk, {brand: tmp.effective_minutes}, **kw)


def emp(eid, brands=("A",), **kw):
    return Employee(eid, eid.capitalize(), {b: PRIORITY for b in brands}, **kw)


def cfg(**kw):
    kw.setdefault("time_limit_s", 20)
    kw.setdefault("workers", 4)
    return SolverConfig(**kw)


def worked_days(res, eid):
    return {a.day for a in res.assignments if a.employee_id == eid}


def minutes(res, eid):
    return sum(a.effective_minutes for a in res.assignments if a.employee_id == eid)


def test_plafond_mensuel_strict_tous_sites_et_marques_cumules():
    """Un seul collaborateur, un shift par jour en alternance sur deux sites et deux marques : jamais plus de 176 h dans le mois,
    même si des shifts restent non couverts (sans plafond, le moteur en prendrait 26 : 208 h)."""
    slots = [slot(f"X|{d}", d, site="S1" if i % 2 else "S2", brand="A" if i % 2 else "B") for i, d in enumerate(NOV)]
    inp = SolverInput(NOV[0], NOV[-1], slots, [emp("ana", ("A", "B"))], [], cfg(monthly_cap_minutes=CAP))
    res = solve(inp)
    assert minutes(res, "ana") <= CAP
    assert minutes(res, "ana") == CAP  # 22 shifts de 8 h : le plafond est atteint, jamais dépassé
    assert {a.allocations and next(iter(a.allocations)) for a in res.assignments} == {"A", "B"}
    assert not res.hard_violations and len(res.uncovered_slots) == 8
    free = solve(SolverInput(NOV[0], NOV[-1], slots, [emp("ana", ("A", "B"))], [], cfg()))
    assert minutes(free, "ana") > CAP  # sans plafond : 26 shifts (jours consécutifs)


def test_plafond_mensuel_compte_les_heures_d_une_periode_voisine_du_meme_mois():
    """Période du 16 au 30 novembre ; 10 shifts de 8 h déjà faits du 2 au 13 novembre : il ne reste que 96 h (12 shifts)."""
    days = NOV[15:]
    slots = [slot(f"X|{d}", d) for d in days]
    out = [OutsideShift("ana", NOV[k], time(9), time(18), 480) for k in range(1, 13) if NOV[k].weekday() != 6][:10]
    inp = SolverInput(days[0], days[-1], slots, [emp("ana")], [], cfg(monthly_cap_minutes=CAP), outside_shifts=out)
    res = solve(inp)
    assert minutes(res, "ana") + sum(o.minutes for o in out) <= CAP
    assert len(res.assignments) == 12 and not res.hard_violations


def test_verificateur_plafond_mensuel_structure():
    slots = [slot(f"X|{d}", d) for d in NOV[:23]]
    assigns = [Assignment(s.id, "ana", s.day, s.start, s.end, 540, 60, 480, dict(s.allocations)) for s in slots]
    inp = SolverInput(NOV[0], NOV[-1], slots, [emp("ana")], [], cfg(monthly_cap_minutes=CAP, max_consecutive_days=31))
    found = [v for v in violations(inp, assigns) if v.code == "MONTHLY_CAP"]
    assert len(found) == 1
    v = found[0]
    assert v.employee == "ana" and len(v.slots) == 23 and v.limit == "176 h" and v.reached == "184 h"
    assert v.text == "MONTHLY_CAP: Ana 11040>10560 minutes en novembre 2026" and v.text in validate(inp, assigns)


def test_maximum_de_jours_par_mois_une_journee_compte_une_fois():
    """Deux shifts possibles par jour (repos minimal ramené à 0 pour l'essai) : 10 jours au plus, mais plusieurs shifts par jour permis."""
    slots = []
    for d in NOV:
        slots += [slot(f"M|{d}", d, start=(6, 0), end=(10, 0), brk=0), slot(f"A|{d}", d, start=(11, 0), end=(15, 0), brk=0)]
    inp = SolverInput(NOV[0], NOV[-1], slots, [emp("ana", max_days_month=10)], [], cfg(rest_hours=0))
    res = solve(inp)
    days = worked_days(res, "ana")
    assert len(days) == 10 and len(res.assignments) == 20  # 10 jours, deux shifts chacun
    assert not res.hard_violations
    bad = [Assignment(s.id, "ana", s.day, s.start, s.end, 240, 0, 240, dict(s.allocations)) for s in slots[:22]]  # 11 jours
    assert any(v.code == "MAX_DAYS_MONTH" and v.reached == "11 jours" for v in violations(inp, bad))


def test_minimum_de_jours_obligatoire_comme_le_maximum():
    slots = [slot(f"X|{d}", d) for d in NOV]
    inp = SolverInput(NOV[0], NOV[-1], slots, [emp("ana", min_days_month=20), emp("ben")], [], cfg())
    res = solve(inp)
    assert len(worked_days(res, "ana")) >= 20 and not res.hard_violations  # sans minimum, l'équité partagerait 15 / 15
    bad = [a for a in res.assignments if a.employee_id != "ana" or a.day.day <= 10]  # Ana : 10 jours au plus
    v = next(v for v in violations(inp, bad) if v.code == "MIN_DAYS_NOT_MET")
    assert v.employee == "ana" and v.limit == "20 jours" and int(v.reached.split()[0]) <= 10


def test_minimum_de_jours_impossible_bloque_le_calcul_avec_la_raison():
    slots = [slot(f"X|{d}", d) for d in NOV]
    inp = SolverInput(NOV[0], NOV[-1], slots, [emp("ana", min_days_month=20, available_weekdays={0, 1, 2}), emp("ben")], [], cfg())
    res = solve(inp)
    assert res.status == "infaisable" and not res.assignments  # jamais un planning qui enfreint le minimum
    issue = next(i for i in res.diagnostics if i.code == "MIN_DAYS_IMPOSSIBLE")
    assert issue.employee == "ana" and issue.severity == "blocking"
    assert "20 jours demandés" in issue.message and "seulement 13 jour(s) possible(s)" in issue.message


def test_minimum_de_jours_incompatible_avec_le_plafond_bloque():
    slots = [slot(f"X|{d}", d) for d in NOV]
    inp = SolverInput(NOV[0], NOV[-1], slots, [emp("ana", min_days_month=25)], [], cfg(monthly_cap_minutes=CAP, max_consecutive_days=31))
    res = solve(inp)
    assert res.status == "infaisable"
    assert "plafond mensuel de 176 h ne permet que 22 jour(s)" in next(i for i in res.diagnostics if i.code == "MIN_DAYS_IMPOSSIBLE").message


def test_minimum_de_jours_et_jours_consecutifs():
    slots = [slot(f"X|{d}", d) for d in NOV]
    res = solve(SolverInput(NOV[0], NOV[-1], slots, [emp("ana", min_days_month=27)], [], cfg()))
    assert "maximum de 6 jours consécutifs ne permet que 26 jour(s)" in next(i for i in res.diagnostics if i.code == "MIN_DAYS_IMPOSSIBLE").message


def test_minimums_compatibles_un_a_un_mais_pas_ensemble():
    """Deux minimums de 20 jours pour 30 shifts : chacun est possible, pas les deux. Le second calcul nomme les collaborateurs en cause."""
    slots = [slot(f"X|{d}", d) for d in NOV]
    res = solve(SolverInput(NOV[0], NOV[-1], slots, [emp("ana", min_days_month=20), emp("ben", min_days_month=20)], [], cfg(time_limit_s=10)))
    assert res.status == "infaisable"
    issue = next(i for i in res.diagnostics if i.code == "MIN_DAYS_CONFLICT")
    assert "Ana (20 jours en novembre 2026)" in issue.message and "Ben (20 jours en novembre 2026)" in issue.message
    assert "leurs minimums cumulés (40 jours) dépassent les 30 shifts" in issue.message


def test_collaborateur_supprime_plus_aucun_shift_apres_son_retrait():
    slots = [slot(f"X|{d}", d) for d in NOV]
    inp = SolverInput(NOV[0], NOV[-1], slots, [emp("ana", left_on=NOV[14]), emp("ben")], [], cfg())
    res = solve(inp)
    assert all(d < NOV[14] for d in worked_days(res, "ana")) and not res.hard_violations
    late = slots[20]
    bad = [Assignment(late.id, "ana", late.day, late.start, late.end, 540, 60, 480, dict(late.allocations))]
    v = next(v for v in violations(inp, bad) if v.code == "EMPLOYEE_REMOVED")
    assert v.slots == [late.id] and "15/11/2026" in v.text


def test_detail_des_incompatibilites_obligatoire_et_preference():
    starts = [slot(f"M|{d}", d, start=(7, 0), end=(16, 0)) for d in NOV[:3]] + [slot(f"S|{d}", d, start=(12, 0), end=(21, 0)) for d in NOV[:3]]
    inp = SolverInput(NOV[0], NOV[-1], starts, [emp("ana", time_pref="matin"), emp("ben", max_days_month=1)], [], cfg())
    plan = [Assignment(s.id, "ana" if s.id.startswith("S") else "ben", s.day, s.start, s.end, 540, 60, 480, dict(s.allocations)) for s in starts]
    rep = compatibility(inp, plan)
    hard = [i for i in rep["items"] if i["kind"] == "obligatoire"]
    soft = [i for i in rep["items"] if i["kind"] == "preference"]
    assert [h["code"] for h in hard] == ["MAX_DAYS_MONTH"] and hard[0]["employee"] == "Ben"
    assert [s["day"] for s in hard[0]["shifts"]] == ["2026-11-01", "2026-11-02", "2026-11-03"] and hard[0]["shifts"][0]["start"] == "07:00"
    assert "3 jours travaillés dans le mois pour un maximum de 1 jours" in hard[0]["reason"]
    assert len(soft) == 3 and all(s["code"] == "TIME_PREF" and s["employee"] == "Ana" and s["shifts"][0]["site"] == "S" for s in soft)
    assert rep["hard"] == validate(inp, plan) and len(rep["items"]) == len(rep["hard"]) + len(rep["soft"])


def test_suivi_du_calcul():
    seen = []
    slots = [slot(f"X|{d}", d) for d in NOV[:7]]
    solve(SolverInput(NOV[0], NOV[6], slots, [emp("ana"), emp("ben")], [], cfg(time_limit_s=5)), progress=seen.append)
    phases = [p["phase"] for p in seen]
    assert phases[0] == "model" and "level" in phases and phases[-1] == "checking"
    lv = next(p for p in seen if p["phase"] == "level")
    assert lv["index"] == 1 and lv["count"] >= 1 and lv["time_limit_s"] == 5 and "elapsed_s" in lv


def test_depassement_fixe_conserve_jamais_aggrave():
    """Réoptimisation locale d'un planning établi avant le plafond : 23 shifts verrouillés (184 h) restent, aucun shift de plus."""
    slots = [slot(f"X|{d}", d) for d in NOV]
    locked = {s.id: "ana" for s in slots[:23]}
    inp = SolverInput(NOV[0], NOV[-1], slots, [emp("ana"), emp("ben")], [], cfg(monthly_cap_minutes=CAP, max_consecutive_days=31), locked=locked)
    res = solve(inp)
    assert res.status in ("optimal", "faisable") and not res.hard_violations
    assert minutes(res, "ana") == 23 * 480  # conservé tel quel, jamais au-delà
    assert all(a.employee_id == "ben" for a in res.assignments if a.slot_id not in locked)
    over = [Assignment(s.id, "ana", s.day, s.start, s.end, 540, 60, 480, dict(s.allocations)) for s in slots[:24]]
    assert any(v.code == "MONTHLY_CAP" for v in violations(inp, over))  # un shift non fixé de plus : aggravation détectée


def test_controles_avant_generation_capacite_creneaux_orphelins_budget():
    from planning_solver.context import prepare
    from planning_solver.diagnostics import pre_generation_checks
    from planning_solver.model import BrandBudget
    slots = [slot(f"X|{d}", d) for d in NOV] + [slot(f"Y|{d}", d, brand="Z") for d in NOV[:2]]  # marque Z : personne n'est autorisé
    inp = SolverInput(NOV[0], NOV[-1], slots, [emp("ana")], [BrandBudget("A", 100 * 60)], cfg(monthly_cap_minutes=CAP))
    codes = {i.code: i for i in pre_generation_checks(prepare(inp))}
    assert "2 shift(s) obligatoire(s) sans aucun collaborateur admissible" in codes["NO_ELIGIBLE_EMPLOYEE"].message
    assert "Capacité maximale de l'effectif : 176 h pour 256 h" in codes["CAPACITY_BELOW_DEMAND"].message  # 32 shifts de 8 h ; une seule personne plafonnée
    assert "A : budget strict de 100 h pour 240 h" in codes["BUDGET_BELOW_DEMAND"].message
    ok = SolverInput(NOV[0], NOV[-1], slots[:30], [emp("ana"), emp("ben")], [], cfg(monthly_cap_minutes=CAP))
    assert pre_generation_checks(prepare(ok)) == []  # aucun faux signalement quand c'est faisable
