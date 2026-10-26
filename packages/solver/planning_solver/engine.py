"""Moteur CP-SAT. Contraintes dures = contraintes du modèle ; préférences = termes de coût."""
from __future__ import annotations

import threading
import time as _time
from collections import defaultdict
from datetime import timedelta
from typing import Dict, List, Optional

from ortools.sat.python import cp_model

from .diagnostics import diagnose_uncovered, missing_data, core_issue
from .model import (Assignment, REINFORCE, Employee, Slot, SolverInput, SolverResult)
from .validator import validate


_UNIT_TERMS = ("fairness", "overtime", "budget")  # termes comptés en unités, pondérés à l'assemblage


def _eligible(e: Employee, s: Slot, locked_slots: Dict[str, str]) -> bool:
    if e.blocked(s.day) or s.tag in e.forbidden_tags:
        return False
    if any(b not in e.brands for b in s.brands):
        return False
    return all(k in e.skills for k in s.required_skills)


def preference_checks(e: Employee, s: Slot) -> List[tuple]:
    """[(code, satisfait, force)] pour les préférences applicables à (employé, slot)."""
    out = []
    if e.latest_start is not None:
        out.append(("start<=%s" % e.latest_start.strftime("%H:%M"), s.start <= e.latest_start, 1))
    if e.preferred_times:
        out.append(("horaire_prefere", (s.start, s.end) in e.preferred_times, 1))
    if e.preferred_tags:
        out.append(("tag_prefere:" + "/".join(sorted(e.preferred_tags)), s.tag in e.preferred_tags,
                    e.preference_strength))
    return out


def _period(s: Slot) -> str:
    h = s.start.hour + s.start.minute / 60
    return "matin" if h < 10 else ("apres_midi" if h >= 12 else "milieu")


def _days(inp: SolverInput):
    d, out = inp.period_start, []
    while d <= inp.period_end:
        out.append(d)
        d += timedelta(days=1)
    return out


def solve(inp: SolverInput, cancel: Optional[threading.Event] = None) -> SolverResult:
    t0 = _time.time()
    cfg, W = inp.config, inp.config.weights
    m = cp_model.CpModel()
    slots = {s.id: s for s in inp.slots}
    emps = {e.id: e for e in inp.employees}
    days = _days(inp)

    x: Dict[tuple, cp_model.IntVar] = {}
    by_emp: Dict[str, List[Slot]] = defaultdict(list)
    for e in inp.employees:
        for s in inp.slots:
            if _eligible(e, s, inp.locked):
                x[e.id, s.id] = m.NewBoolVar(f"x_{e.id}_{s.id}")
                by_emp[e.id].append(s)

    y: Dict[str, cp_model.IntVar] = {}  # slot pourvu
    for s in inp.slots:
        y[s.id] = m.NewBoolVar(f"y_{s.id}")
        vs = [x[e.id, s.id] for e in inp.employees if (e.id, s.id) in x]
        m.Add(sum(vs) == y[s.id])  # une seule personne par shift (aucune double affectation)

    groups: Dict[str, List[Slot]] = defaultdict(list)
    for s in inp.slots:
        if s.day_group:
            groups[s.day_group].append(s)
    for g in groups.values():
        m.Add(sum(y[s.id] for s in g) <= 1)

    # Verrous : l'affectation est imposée, mais reste soumise aux contraintes dures (sinon infaisable)
    for sid, eid in inp.locked.items():
        if (eid, sid) in x:
            m.Add(x[eid, sid] == 1)
        else:
            m.AddBoolOr([])  # verrou incompatible avec les règles dures -> infaisable, expliqué en diagnostic

    # Chevauchement + repos minimal (inclut double affectation multi-sites)
    rest = timedelta(hours=cfg.rest_hours)
    ordered = sorted(inp.slots, key=lambda s: s.bounds[0])
    for e in inp.employees:
        mine = [s for s in ordered if (e.id, s.id) in x]
        for i, a in enumerate(mine):
            ea = a.bounds[1]
            for b in mine[i + 1:]:
                if b.bounds[0] - ea >= rest:
                    break
                m.AddBoolOr([x[e.id, a.id].Not(), x[e.id, b.id].Not()])
        # note: break valide car trié par début ; les chevauchements antérieurs sont couverts par la boucle

    # Jours travaillés
    worked: Dict[tuple, cp_model.IntVar] = {}
    loc: Dict[tuple, cp_model.IntVar] = {}
    for e in inp.employees:
        for d in days:
            xs = [x[e.id, s.id] for s in by_emp[e.id] if s.day == d]
            if not xs:
                continue
            w = m.NewBoolVar(f"w_{e.id}_{d}")
            for v in xs:
                m.Add(v <= w)
            m.Add(w <= sum(xs))
            worked[e.id, d] = w

    def wk(e_id, d):
        return worked.get((e_id, d))

    terms: Dict[str, list] = defaultdict(list)

    for e in inp.employees:
        # jours consécutifs (fenêtre glissante)
        L = cfg.max_consecutive_days
        for i in range(len(days) - L):
            win = [wk(e.id, d) for d in days[i:i + L + 1]]
            win = [v for v in win if v is not None]
            if len(win) > L:
                m.Add(sum(win) <= L)
        if e.prior_consecutive_days:
            k = L - e.prior_consecutive_days
            head = [wk(e.id, d) for d in days[:k + 1]]
            head = [v for v in head if v is not None]
            if k >= 0 and len(head) > k:
                m.Add(sum(head) <= k)
        # semaines ISO
        weeks: Dict[tuple, list] = defaultdict(list)
        for d in days:
            weeks[d.isocalendar()[:2]].append(d)
        for wkey, wdays in weeks.items():
            vs = [wk(e.id, d) for d in wdays if wk(e.id, d) is not None]
            if e.max_days_per_week is not None and len(vs) > e.max_days_per_week:
                m.Add(sum(vs) <= e.max_days_per_week)
            if e.weekly_rest_days_pref is not None and len(wdays) == 7 and vs:
                cap = 7 - e.weekly_rest_days_pref
                if e.weekly_rest_days_hard:
                    m.Add(sum(vs) <= cap)
                else:
                    ex = m.NewIntVar(0, 7, f"rd_{e.id}_{wkey}")
                    m.Add(ex >= sum(vs) - cap)
                    terms["rest_days"].append(W["rest_days"] * ex)
            c = e.contract
            if c and c.weekly_max_minutes is not None:
                m.Add(sum(x[e.id, s.id] * s.effective_minutes for s in by_emp[e.id]
                          if s.day in wdays) <= c.weekly_max_minutes)
        c = e.contract
        tot = sum(x[e.id, s.id] * s.effective_minutes for s in by_emp[e.id])
        if c and c.monthly_max_minutes is not None and not c.overtime_allowed:
            m.Add(tot <= c.monthly_max_minutes)
        if c and c.monthly_target_minutes is not None:
            ot = m.NewIntVar(0, 1000, f"ot_{e.id}")  # heures
            m.Add(60 * ot >= tot - c.monthly_target_minutes)
            terms["overtime"].append(ot)
        # fatigue : 5 jours consécutifs
        for i in range(len(days) - 4):
            win = [wk(e.id, d) for d in days[i:i + 5]]
            win = [v for v in win if v is not None]
            if len(win) == 5:
                f = m.NewBoolVar(f"fat_{e.id}_{i}")
                m.Add(f >= sum(win) - 4)
                terms["fatigue"].append(W["fatigue"] * f)

    # Couverture obligatoire
    assump = {}
    for s in inp.slots:
        if s.mandatory:
            hrs = max(1, round(s.effective_minutes / 60))
            if cfg.strict_coverage:
                lit = m.NewBoolVar(f"cov_{s.id}")
                m.AddImplication(lit, y[s.id])
                assump[s.id] = lit
            else:
                terms["coverage"].append(W["coverage"] * hrs * (1 - y[s.id]))
    if assump:
        m.AddAssumptions(list(assump.values()))

    # Budgets : plafond dur, écart pénalisé pour les marques à shifts optionnels
    optional_brands = {b for s in inp.slots if not s.mandatory for b in s.brands}
    for b in inp.budgets:
        planned = sum(y[s.id] * s.allocations[b.brand] for s in inp.slots if b.brand in s.allocations)
        m.Add(planned <= b.target_minutes)
        if b.brand in optional_brands:
            sh = m.NewIntVar(0, b.target_minutes // 60 + 1, f"short_{b.brand}")  # heures
            m.Add(60 * sh >= b.target_minutes - planned)
            terms["budget"].append(sh)

    # Renfort
    for e in inp.employees:
        for s in by_emp[e.id]:
            if any(e.brands[b] == REINFORCE for b in s.brands):
                terms["reinforce"].append(W["reinforce"] * max(1, round(s.effective_minutes / 60)) * x[e.id, s.id])

    # Préférences individuelles
    for e in inp.employees:
        for s in by_emp[e.id]:
            for _code, ok, force in preference_checks(e, s):
                if not ok:
                    terms["preference"].append(W["preference"] * force * x[e.id, s.id])

    # Équité relative : cible proportionnelle au poids x disponibilité (ou cible contrat si renseignée)
    supply = sum(s.effective_minutes for s in inp.slots if s.mandatory)
    supply += sum(b.target_minutes for b in inp.budgets if b.brand in optional_brands)
    caps, raw = {}, {}
    for e in inp.employees:
        avail = sum(1 for d in days if not e.blocked(d))
        c = e.contract
        raw[e.id] = c.monthly_target_minutes if c and c.monthly_target_minutes else e.weight * avail
        caps[e.id] = sum(s.effective_minutes for s in by_emp[e.id])
    Wsum = sum(raw.values()) or 1
    for e in inp.employees:
        tgt = min(int(supply * raw[e.id] / Wsum), caps[e.id])
        if not by_emp[e.id]:
            continue
        tot = sum(x[e.id, s.id] * s.effective_minutes for s in by_emp[e.id])
        dev = m.NewIntVar(0, 100000, f"dev_{e.id}")  # demi-heures
        m.Add(30 * dev >= tot - tgt)
        m.Add(30 * dev >= tgt - tot)
        terms["fairness"].append(dev)

    # Changements de site
    for e in inp.employees:
        sites = sorted({s.site for s in by_emp[e.id]})
        if len(sites) < 2:
            continue
        for d in days:
            for st in sites:
                xs = [x[e.id, s.id] for s in by_emp[e.id] if s.day == d and s.site == st]
                if xs:
                    v = m.NewBoolVar(f"loc_{e.id}_{d}_{st}")
                    m.Add(v == sum(xs))
                    loc[e.id, d, st] = v
        for i, d in enumerate(days[:-1]):
            nxt = days[i + 1]
            wn = wk(e.id, nxt)
            if wn is None:
                continue
            for st in sites:
                a = loc.get((e.id, d, st))
                if a is None:
                    continue
                b = loc.get((e.id, nxt, st))
                c = m.NewBoolVar(f"chg_{e.id}_{d}_{st}")
                m.Add(c >= a + wn - (b if b is not None else 0) - 1)
                terms["site_change"].append(W["site_change"] * c)

    # Équilibre ouvertures / fermetures / week-ends : minimiser le maximum individuel
    for name, pred in (("open", lambda s: s.tag == "open"), ("close", lambda s: s.tag == "close"),
                       ("weekend", lambda s: s.day.weekday() >= 5)):
        mx = m.NewIntVar(0, 100, f"max_{name}")
        for e in inp.employees:
            xs = [x[e.id, s.id] for s in by_emp[e.id] if pred(s)]
            if xs:
                m.Add(mx >= sum(xs))
        terms["balance"].append(W["balance"] * mx)

    # Famille : horaires opposés quand les deux travaillent le même jour
    for e in inp.employees:
        if not e.opposite_of or e.opposite_of not in emps or e.id > e.opposite_of:
            continue
        for d in days:
            for per in ("matin", "milieu", "apres_midi"):
                a = [x[e.id, s.id] for s in by_emp[e.id] if s.day == d and _period(s) == per]
                b = [x[e.opposite_of, s.id] for s in by_emp[e.opposite_of] if s.day == d and _period(s) == per]
                if a and b:
                    v = m.NewBoolVar(f"fam_{e.id}_{d}_{per}")
                    m.Add(v >= sum(a) + sum(b) - 1)
                    terms["family"].append(W["family"] * v)

    # Coordination cosmétique : prises de poste décalées
    sg: Dict[tuple, List[Slot]] = defaultdict(list)
    for s in inp.slots:
        if s.stagger_group:
            sg[s.stagger_group, s.day].append(s)
    for (_g, _d), ss in sg.items():
        for i, a in enumerate(ss):
            for b in ss[i + 1:]:
                if a.brands == b.brands:
                    continue
                gap = abs((a.bounds[0] - b.bounds[0]).total_seconds()) / 60
                if gap < cfg.stagger_minutes:
                    v = m.NewBoolVar(f"stg_{a.id}_{b.id}")
                    m.Add(v >= y[a.id] + y[b.id] - 1)
                    terms["stagger"].append(W["stagger"] * v)

    # Stabilité
    for sid, eid in inp.previous.items():
        if (eid, sid) in x and sid not in inp.locked:
            terms["stability"].append(W["stability"] * (1 - x[eid, sid]))
        elif sid in slots and sid not in inp.locked:
            terms["stability"].append(W["stability"] * 1)

    # Assemblage : les termes en minutes sont pondérés en entiers
    exprs: Dict[str, cp_model.LinearExprT] = {}
    for k, lst in terms.items():
        if not lst:
            continue
        exprs[k] = sum(lst)
    scaled = [ex * W[k] if k in _UNIT_TERMS else ex for k, ex in exprs.items()]
    m.Minimize(sum(scaled) if scaled else 0)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = cfg.time_limit_s
    solver.parameters.num_workers = cfg.workers
    solver.parameters.random_seed = cfg.seed
    stopped = {"v": False}
    watcher = None
    if cancel is not None:
        def _watch():
            while not stopped["v"]:
                if cancel.wait(0.1):
                    solver.StopSearch()
                    return
        watcher = threading.Thread(target=_watch, daemon=True)
        watcher.start()
    status = solver.Solve(m)
    stopped["v"] = True
    dur = _time.time() - t0

    names = {cp_model.OPTIMAL: "optimal", cp_model.FEASIBLE: "faisable"}
    missing = missing_data(inp)
    base = dict(duration_s=round(dur, 3), weights=dict(W), missing_data=missing)
    exploratory = any(i.severity in ("blocking", "warning") and i.code in ("CONTRACT_MISSING",) for i in missing)
    mode = "simulation_exploratoire" if exploratory else "validable"

    if status in (cp_model.INFEASIBLE, cp_model.MODEL_INVALID) or status == cp_model.UNKNOWN:
        diag = []
        if status == cp_model.INFEASIBLE:
            diag = [core_issue(inp, solver, assump)] if assump else []
            diag += diagnose_uncovered(inp, [s.id for s in inp.slots if s.mandatory], inp.locked)
            st = "infaisable"
        else:
            st = "interrompu"
            diag = []
        return SolverResult(status=st, mode=mode, validable=False, assignments=[], uncovered_slots=[],
                            budgets=[], objective={}, preferences={}, avoided_violations={},
                            hard_violations=[], employee_hours={}, diagnostics=diag, **base)

    assigns: List[Assignment] = []
    for (eid, sid), v in x.items():
        if solver.Value(v):
            s = slots[sid]
            h = s.hours
            assigns.append(Assignment(sid, eid, s.day, s.start, s.end, h.presence_minutes, h.break_minutes,
                                      h.effective_minutes, dict(s.allocations), locked=inp.locked.get(sid) == eid))
    assigns.sort(key=lambda a: (a.day, a.start, a.slot_id))
    filled = {a.slot_id for a in assigns}
    uncovered = [s.id for s in inp.slots if s.mandatory and s.id not in filled]

    planned: Dict[str, int] = defaultdict(int)
    for a in assigns:
        for b, mi in a.allocations.items():
            planned[b] += mi
    budgets = []
    for b in inp.budgets:
        budgets.append({"brand": b.brand, "target_minutes": b.target_minutes, "planned_minutes": planned[b.brand],
                        "remaining_minutes": b.target_minutes - planned[b.brand],
                        "requirements_defined": b.requirements_defined})
    # un budget sans besoins définis (Lindt/Toblerone) reste « non planifié » : jamais un succès complet
    shortfall = any(bd["remaining_minutes"] > 0 for bd in budgets)
    objective = {}
    for k, ex in exprs.items():
        val = int(solver.Value(ex))
        objective[k] = val * (W[k] if k in _UNIT_TERMS else 1)

    prefs: Dict[str, dict] = defaultdict(lambda: {"satisfaites": 0, "non_satisfaites": 0})
    for a in assigns:
        e, s = emps[a.employee_id], slots[a.slot_id]
        for code, ok, _f in preference_checks(e, s):
            prefs[f"{e.name}:{code}"]["satisfaites" if ok else "non_satisfaites"] += 1
    _derived_metrics(inp, assigns, prefs)

    hours: Dict[str, int] = defaultdict(int)
    for a in assigns:
        hours[a.employee_id] += a.effective_minutes

    viol = validate(inp, assigns)
    st = names.get(status, "faisable")
    if cancel is not None and cancel.is_set():
        st = "interrompu"
    elif uncovered or shortfall:
        st = "partiellement_couvert"
    diag = diagnose_uncovered(inp, uncovered, inp.locked) if uncovered else []
    avoided = {"conflits_chevauchement_repos": _count_conflict_pairs(inp, x)}
    return SolverResult(status=st, mode=mode, validable=(mode == "validable" and st in ("optimal", "faisable")
                                                          and not viol),
                        assignments=assigns, uncovered_slots=uncovered, budgets=budgets, objective=objective,
                        preferences=dict(prefs), avoided_violations=avoided, hard_violations=viol,
                        employee_hours=dict(hours), diagnostics=diag, **base)


def _count_conflict_pairs(inp: SolverInput, x: dict) -> int:
    """Nombre de couples (employé, 2 slots) interdits par chevauchement/repos : violations évitées."""
    rest = timedelta(hours=inp.config.rest_hours)
    n = 0
    ordered = sorted(inp.slots, key=lambda s: s.bounds[0])
    for e in inp.employees:
        mine = [s for s in ordered if (e.id, s.id) in x]
        for i, a in enumerate(mine):
            for b in mine[i + 1:]:
                if b.bounds[0] - a.bounds[1] >= rest:
                    break
                n += 1
    return n


def _derived_metrics(inp: SolverInput, assigns: List[Assignment], prefs: dict) -> None:
    slots = {s.id: s for s in inp.slots}
    emps = {e.id: e for e in inp.employees}
    by_day_emp: Dict[tuple, Slot] = {(a.employee_id, a.day): slots[a.slot_id] for a in assigns}
    for e in inp.employees:
        if e.opposite_of and e.id < e.opposite_of and e.opposite_of in emps:
            for d in {a.day for a in assigns if a.employee_id == e.id}:
                o = by_day_emp.get((e.opposite_of, d))
                if o is not None:
                    ok = _period(by_day_emp[e.id, d]) != _period(o)
                    prefs[f"famille:{e.name}/{emps[e.opposite_of].name}"][
                        "satisfaites" if ok else "non_satisfaites"] += 1
    cos: Dict[object, List[Slot]] = defaultdict(list)
    for a in assigns:
        s = slots[a.slot_id]
        if s.stagger_group:
            cos[s.day].append(s)
    for d, ss in cos.items():
        for i, a in enumerate(ss):
            for b in ss[i + 1:]:
                if a.brands != b.brands:
                    gap = abs((a.bounds[0] - b.bounds[0]).total_seconds()) / 60
                    prefs["decalage_cosmetique"]["satisfaites" if gap >= inp.config.stagger_minutes
                                                  else "non_satisfaites"] += 1
