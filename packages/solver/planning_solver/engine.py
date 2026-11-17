"""Moteur CP-SAT. Contraintes dures = contraintes du modèle ; préférences = termes de coût.

Modélisation : une variable de décision x[e, s] par affectation ADMISSIBLE (préfiltrage : `context.ineligibility`), jamais pour une
affectation impossible. Optimisation hiérarchisée (`SolverConfig.hierarchical`) : les contraintes dures priment toujours, puis la
couverture est optimisée et figée, puis les engagements (objectifs contractuels, quotas exacts, budgets souples), puis tous les
autres critères pondérés. Le statut « optimal » n'est annoncé que si le solveur l'a PROUVÉ à chaque niveau."""
from __future__ import annotations

import threading
import time as _time
from collections import defaultdict
from datetime import timedelta
from typing import Callable, Dict, List, Optional

from ortools.sat.python import cp_model

from .context import (cost_units, coverage_cost, hours_units, individual_penalty, ineligibility, min_days_need, period_of, prepare,
                      preference_checks, relation_pairs, scoped_avoid_pairs, history_excess)
from .diagnostics import diagnose_uncovered, min_days_blockers, min_days_core_issue, min_days_group_conflicts, missing_data, core_issue
from .metrics import plan_metrics
from .model import (Assignment, DEFAULT_WEIGHTS, Issue, LEVELS, REINFORCE, SECONDARY, Slot, SolverInput, SolverResult)
from .objective import evaluate
from .sundays import sunday_summary
from .validator import validate


_UNIT_TERMS = ("fairness", "overtime", "budget")  # termes comptés en unités, pondérés à l'assemblage


class _StopAtZero(cp_model.CpSolverSolutionCallback):
    """Un coût nul ne peut plus s'améliorer : inutile de consommer le temps de calcul à le prouver. Compte aussi les solutions
    trouvées (suivi de la génération)."""

    def __init__(self, on_solution: Optional[Callable[[int, float], None]] = None):
        super().__init__()
        self.count = 0
        self._on = on_solution

    def on_solution_callback(self) -> None:
        self.count += 1
        if self._on is not None:
            self._on(self.count, self.ObjectiveValue())
        if self.ObjectiveValue() == 0:
            self.StopSearch()


def _level_groups(cfg, exprs: dict, has_previous: bool) -> List[tuple]:
    """Niveaux d'optimisation : (nom, termes). Sans hiérarchie, un seul niveau (somme pondérée)."""
    keys = list(exprs)
    if not cfg.hierarchical:
        return [("pondere", keys)]
    out, used = [], set()
    for name, terms in LEVELS:
        if terms is None:
            continue
        chosen = [k for k in terms if k in exprs]
        if name == "engagements" and has_previous and "stability" in exprs:
            chosen.append("stability")  # réoptimisation : ne pas bouleverser le planning passe avant le confort
        used.update(chosen)
        out.append((name, chosen))
    out.append((LEVELS[-1][0], [k for k in keys if k not in used]))
    return [g for g in out if g[1]]


Progress = Callable[[dict], None]


def solve(inp: SolverInput, cancel: Optional[threading.Event] = None, progress: Optional[Progress] = None) -> SolverResult:
    """`progress` (facultatif) reçoit l'état du calcul : préparation, niveau en cours, solutions trouvées, temps écoulé."""
    t0 = _time.time()

    def report(**kw) -> None:
        if progress is not None:
            try:
                progress({"elapsed_s": round(_time.time() - t0, 1), "time_limit_s": inp.config.time_limit_s, **kw})
            except Exception:  # noqa: BLE001 — le suivi ne doit jamais interrompre le calcul
                pass

    report(phase="model")
    cfg = inp.config
    W = {**DEFAULT_WEIGHTS, **cfg.weights}
    m = cp_model.CpModel()
    prep = prepare(inp)
    slots, emps, days = prep.slots, prep.emps, prep.days
    by_emp = prep.by_emp

    # minimum de jours impossible à lui seul (jours possibles, maximum, plafond, limite hebdomadaire, jours consécutifs) : blocage expliqué
    # minimums incompatibles entre collaborateurs qui se partagent les mêmes shifts : dénombrement, indépendant du temps de calcul
    blockers = min_days_blockers(prep) + min_days_group_conflicts(prep)
    if blockers:
        report(phase="checking")
        return SolverResult(status="infaisable", mode="simulation_exploratoire" if any(i.code == "CONTRACT_MISSING" for i in missing_data(inp)) else "validable",
                            validable=False, duration_s=round(_time.time() - t0, 3), assignments=[], uncovered_slots=[], budgets=[], objective={},
                            weights=dict(W), preferences={}, avoided_violations={}, missing_data=missing_data(inp), diagnostics=blockers,
                            hard_violations=[], employee_hours={}, sunday=sunday_summary(inp))

    x: Dict[tuple, cp_model.IntVar] = {}
    for e in inp.employees:
        for s in by_emp[e.id]:
            x[e.id, s.id] = m.NewBoolVar(f"x_{e.id}_{s.id}")

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
    impossible_locks = []
    for sid, eid in inp.locked.items():
        if (eid, sid) in x:
            m.Add(x[eid, sid] == 1)
        else:
            impossible_locks.append((sid, eid))
            m.AddBoolOr([])  # verrou incompatible avec les règles dures -> infaisable, expliqué en diagnostic
    for sid in inp.frozen_empty:
        if sid in y:
            m.Add(y[sid] == 0)

    # Chevauchement + repos minimal (inclut double affectation multi-sites)
    rest = timedelta(hours=cfg.rest_hours)
    # temps de déplacement entre sites : l'écart exigé est le plus grand des deux (repos quotidien, déplacement)
    reach = max([rest] + [timedelta(minutes=v) for v in inp.travel_minutes.values()])
    ordered = sorted(inp.slots, key=lambda s: s.bounds[0])
    for e in inp.employees:
        mine = [s for s in ordered if (e.id, s.id) in x]
        for i, a in enumerate(mine):
            ea = a.bounds[1]
            for b in mine[i + 1:]:
                gap = b.bounds[0] - ea
                if gap >= reach:
                    break
                if gap >= rest and gap >= timedelta(minutes=inp.travel(a.site, b.site)):
                    continue
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

    # Jours travaillés hors période (périodes voisines) + jours consécutifs déjà en cours avant la période
    out_days: Dict[str, set] = defaultdict(set)
    for o in inp.outside_shifts:
        if not (inp.period_start <= o.day <= inp.period_end):
            out_days[o.employee_id].add(o.day)
    for e in inp.employees:
        for k in range(1, e.prior_consecutive_days + 1):
            out_days[e.id].add(inp.period_start - timedelta(days=k))

    def wterm(e_id, d):
        """Variable « jour travaillé » dans la période, constante 0/1 hors période, None si aucun shift possible."""
        if inp.period_start <= d <= inp.period_end:
            return wk(e_id, d)
        return 1 if d in out_days[e_id] else 0

    terms: Dict[str, list] = defaultdict(list)
    min_lits: Dict[tuple, cp_model.IntVar] = {}
    outside_minutes: Dict[tuple, int] = defaultdict(int)
    for o in inp.outside_shifts:
        outside_minutes[o.employee_id, o.day.isocalendar()[:2]] += o.minutes

    for e in inp.employees:
        # jours consécutifs (fenêtre glissante, y compris sur la frontière avec les périodes voisines)
        L = cfg.max_consecutive_days
        span = [inp.period_start + timedelta(days=k) for k in range(-L, (inp.period_end - inp.period_start).days + 1 + L)]
        for i in range(len(span) - L):
            win = span[i:i + L + 1]
            if not any(inp.period_start <= d <= inp.period_end for d in win):
                continue
            terms_w = [wterm(e.id, d) for d in win]
            vs_ = [t for t in terms_w if t is not None and not isinstance(t, int)]
            const = sum(t for t in terms_w if isinstance(t, int))
            if len(vs_) + const > L and vs_:
                m.Add(sum(vs_) <= max(0, L - const))
        # semaines ISO (y compris les semaines à cheval sur deux périodes) : limite de jours par semaine
        weeks: Dict[tuple, list] = defaultdict(list)
        for d in days:
            weeks[d.isocalendar()[:2]].append(d)
        week_cap = e.max_days_per_week
        if e.max_days_count is not None and e.max_days_period == "week":
            week_cap = e.max_days_count if week_cap is None else min(week_cap, e.max_days_count)
        for wkey, wdays in weeks.items():
            vs = [wk(e.id, d) for d in wdays if wk(e.id, d) is not None]
            if week_cap is not None and vs:
                full = [d0 for d0 in (min(wdays) - timedelta(days=min(wdays).weekday()) + timedelta(days=k) for k in range(7))]
                terms_w = [wterm(e.id, d0) for d0 in full]
                vs_w = [t for t in terms_w if t is not None and not isinstance(t, int)]
                const = sum(t for t in terms_w if isinstance(t, int))
                if vs_w:
                    m.Add(sum(vs_w) <= max(0, week_cap - const))
            if e.weekly_rest_days_pref is not None and len(wdays) == 7 and vs:
                cap = 7 - e.weekly_rest_days_pref
                if e.weekly_rest_days_hard:
                    m.Add(sum(vs) <= cap)
                else:
                    ex = m.NewIntVar(0, 7, f"rd_{e.id}_{wkey}")
                    m.Add(ex >= sum(vs) - cap)
                    terms["rest_days"].append(W["rest_days"] * ex)
            # plafonds hebdomadaires du contrat et du régime applicable, y compris les heures d'une période voisine dans la même semaine
            c = e.contract
            caps = [v for v in (c.weekly_max_minutes if c else None, e.legal_weekly_max_minutes) if v is not None]
            if caps:
                mine_w = [s for s in by_emp[e.id] if s.day in wdays]
                if mine_w:
                    m.Add(sum(x[e.id, s.id] * s.effective_minutes for s in mine_w) <= max(0, min(caps) - outside_minutes[e.id, wkey]))
        if e.max_days_count is not None and e.max_days_period == "month":
            vs_m = [wk(e.id, d) for d in days if wk(e.id, d) is not None]
            if len(vs_m) > e.max_days_count:
                m.Add(sum(vs_m) <= e.max_days_count)
        # quota de dimanches : plafond dur ; « objectif exact » = manque pénalisé ; jamais 2 shifts le même dimanche
        suns = prep.suns
        if suns and e.sunday_quota is not None:
            sv = [wk(e.id, d) for d in suns if wk(e.id, d) is not None]
            cap = min(e.sunday_quota, len(suns))
            if sv:
                m.Add(sum(sv) <= cap)
                if e.sunday_mode == "exact" and cap > 0:
                    # le manque est borné par les dimanches réellement possibles (disponibilités) pour ne pas fausser le coût
                    short = m.NewIntVar(0, cap, f"sunq_{e.id}")
                    m.Add(short >= cap - sum(sv))
                    terms["sunday_quota"].append(W["sunday_quota"] * short)
        for d in suns:
            xs_d = [x[e.id, s.id] for s in by_emp[e.id] if s.day == d]
            if len(xs_d) > 1:
                m.AddAtMostOne(xs_d)
        c = e.contract
        tot = sum(x[e.id, s.id] * s.effective_minutes for s in by_emp[e.id])
        if c and c.monthly_max_minutes is not None and not c.overtime_allowed:
            m.Add(tot <= c.monthly_max_minutes)
        # par mois civil : plafond d'heures de l'entreprise (tous sites, toutes marques), jours maximum (dur) et minimum (engagement) ;
        # une journée compte une seule fois, même avec plusieurs affectations ; les jours et heures d'une période voisine du même mois comptent
        for mkey, mdays in prep.months.items():
            mine_m = [s for s in by_emp[e.id] if (s.day.year, s.day.month) == mkey]
            if cfg.monthly_cap_minutes is not None and mine_m:
                # heures déjà fixées (verrous, hors périmètre d'une réoptimisation locale) au-delà du plafond : conservées, jamais aggravées
                fixed = sum(s.effective_minutes for s in mine_m if inp.locked.get(s.id) == e.id)
                room = max(0, cfg.monthly_cap_minutes - prep.outside_month_minutes.get((e.id, mkey), 0), fixed)
                if sum(s.effective_minutes for s in mine_m) > room:
                    m.Add(sum(x[e.id, s.id] * s.effective_minutes for s in mine_m) <= room)
            dv = [wk(e.id, d) for d in mdays if wk(e.id, d) is not None]
            done = len(prep.outside_month_days.get((e.id, mkey), ()))
            if e.max_days_month is not None and dv and len(dv) + done > e.max_days_month:
                m.Add(sum(dv) <= max(0, e.max_days_month - done))
            need = min_days_need(prep, e, mkey) if not (e.excluded or e.left_on is not None) else 0
            if need and dv:  # minimum de jours : contrainte dure, comme le maximum
                ct = m.Add(sum(dv) >= need)
                if cfg.min_days_core:
                    lit = m.NewBoolVar(f"mind_{e.id}_{mkey[0]}_{mkey[1]}")
                    ct.OnlyEnforceIf(lit)
                    min_lits[e.id, mkey] = lit
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

    # Couverture obligatoire (pondérée par la priorité du besoin)
    assump = {}
    for s in inp.slots:
        if s.mandatory:
            if cfg.strict_coverage:
                lit = m.NewBoolVar(f"cov_{s.id}")
                m.AddImplication(lit, y[s.id])
                assump[s.id] = lit
            else:
                terms["coverage"].append(coverage_cost(W["coverage"], s) * (1 - y[s.id]))
    if assump or min_lits:
        m.AddAssumptions(list(assump.values()) + list(min_lits.values()))

    # Budgets : plafond dur, écart pénalisé pour les marques à shifts optionnels
    optional_brands = prep.optional_brands
    for b in inp.budgets:
        planned = sum(y[s.id] * s.allocations[b.brand] for s in inp.slots if b.brand in s.allocations)
        if b.strict:
            m.Add(planned <= b.target_minutes)  # budget strict : jamais dépassé
        else:
            over = m.NewIntVar(0, 100000, f"over_{b.brand}")  # heures au-delà du budget (souple)
            m.Add(60 * over >= planned - b.target_minutes)
            terms["budget_over"].append(W["budget_over"] * over)
        if b.brand in optional_brands:
            sh = m.NewIntVar(0, b.target_minutes // 60 + 1, f"short_{b.brand}")  # heures
            m.Add(60 * sh >= b.target_minutes - planned)
            terms["budget"].append(sh)

    # Renfort, coût estimé (si le coût horaire est renseigné)
    for e in inp.employees:
        for s in by_emp[e.id]:
            lv = [e.brands[b] for b in s.brands]
            unit = W["reinforce"] if REINFORCE in lv else (W["secondary"] if SECONDARY in lv else 0)
            if unit:
                terms["reinforce"].append(unit * hours_units(s) * x[e.id, s.id])
            francs = cost_units(e, s)
            if francs and W["cost"]:
                terms["cost"].append(W["cost"] * francs * x[e.id, s.id])

    # Préférences individuelles
    for e in inp.employees:
        for s in by_emp[e.id]:
            for _code, ok, force in preference_checks(e, s):
                if not ok:
                    terms["preference"].append(W["preference"] * force * x[e.id, s.id])

    # Préférence horaire souple (matin / middle / soir) : pénalité par shift hors catégorie
    for e in inp.employees:
        if e.time_pref and not e.time_pref_strict:
            for s in by_emp[e.id]:
                cat = prep.category[s.id]
                if cat is not None and cat != e.time_pref:
                    terms["time_pref"].append(W["time_pref"] * max(1, e.preference_strength) * x[e.id, s.id])

    # Équité relative : cible proportionnelle au poids x disponibilité (ou cible contrat si renseignée)
    for e in inp.employees:
        tgt = prep.targets[e.id]
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

    # Horaires opposés quand les deux travaillent le même jour (préférence paramétrée, aucun nom dans le moteur)
    for e in inp.employees:
        if not e.opposite_of or e.opposite_of not in emps or e.id > e.opposite_of:
            continue
        for d in days:
            for per in ("matin", "milieu", "apres_midi"):
                a = [x[e.id, s.id] for s in by_emp[e.id] if s.day == d and period_of(s) == per]
                b = [x[e.opposite_of, s.id] for s in by_emp[e.opposite_of] if s.day == d and period_of(s) == per]
                if a and b:
                    v = m.NewBoolVar(f"fam_{e.id}_{d}_{per}")
                    m.Add(v >= sum(a) + sum(b) - 1)
                    terms["family"].append(W["family"] * v)

    # Relations entre collaborateurs (même jour, même site) : éviter, binôme, tuteur
    def at(eid, d, st):
        return [x[eid, s.id] for s in by_emp[eid] if s.day == d and s.site == st]

    for kind, e, others, strict, scope in relation_pairs(prep):
        if kind == "avoid_together" and scope != "site_day":
            # même jour tous sites (une pénalité par jour) ou horaires qui se chevauchent (une par paire de shifts)
            per_day: Dict = {}
            for d, a, o, b in scoped_avoid_pairs(prep, e.id, others, scope):
                pair = x[e.id, a.id] + x[o, b.id]
                if strict:
                    m.Add(pair <= 1)
                    continue
                if scope == "day":
                    if d not in per_day:
                        per_day[d] = m.NewBoolVar(f"rel_day_{e.id}_{d}")
                        terms["family"].append(W["family"] * per_day[d])
                    m.Add(per_day[d] >= pair - 1)
                else:
                    v = m.NewBoolVar(f"rel_ovl_{e.id}_{a.id}_{b.id}")
                    m.Add(v >= pair - 1)
                    terms["family"].append(W["family"] * v)
            continue
        for d in days:
            for st in sorted({s.site for s in by_emp[e.id] if s.day == d}):
                a = at(e.id, d, st)
                b = [v for o in others for v in at(o, d, st)]
                if kind == "avoid_together":
                    if a and b:
                        if strict:
                            m.Add(sum(a) + sum(b) <= 1)
                        else:
                            v = m.NewBoolVar(f"rel_{kind}_{e.id}_{d}_{st}")
                            m.Add(v >= sum(a) + sum(b) - 1)
                            terms["family"].append(W["family"] * v)
                elif kind == "mentor":
                    if strict:
                        m.Add(sum(a) <= sum(b))
                    else:
                        v = m.NewBoolVar(f"rel_{kind}_{e.id}_{d}_{st}")
                        m.Add(v >= sum(a) - sum(b))
                        terms["family"].append(W["family"] * v)
                else:  # work_together : pénalité pour le collaborateur présent sans son binôme
                    v = m.NewBoolVar(f"rel_{kind}_{e.id}_{d}_{st}")
                    m.Add(v >= sum(a) - sum(b))
                    terms["family"].append(W["family"] * v)
        if kind == "work_together":  # sens inverse : le binôme présent sans ce collaborateur
            o = others[0]
            for d in days:
                for st in sorted({s.site for s in by_emp[o] if s.day == d}):
                    v = m.NewBoolVar(f"rel_{kind}_{o}_{d}_{st}")
                    m.Add(v >= sum(at(o, d, st)) - sum(at(e.id, d, st)))
                    terms["family"].append(W["family"] * v)

    # Priorité individuelle : à couverture égale, les collaborateurs de plus fort poids d'allocation sont préférés
    if prep.wmax > 0:
        for e in inp.employees:
            pen = individual_penalty(prep, e)
            if pen:
                for s in by_emp[e.id]:
                    terms["individual"].append(W["individual"] * pen * hours_units(s) * x[e.id, s.id])

    # Équité sur plusieurs mois : un shift de week-end (ou de dimanche) coûte davantage à qui en a eu plus que la moyenne auparavant
    if W.get("history"):
        for (eid, key), ex in history_excess(prep).items():
            for s in by_emp.get(eid, ()):
                if (key == "weekends" and s.day.weekday() >= 5) or (key == "sundays" and s.day.weekday() == 6):
                    terms["history"].append(W["history"] * ex * x[eid, s.id])

    # Équilibrage des dimanches (collaborateurs sans quota) et des jours travaillés : minimiser le maximum individuel
    suns_all = prep.suns
    mx_sun = m.NewIntVar(0, len(suns_all), "max_sundays")
    mx_days = m.NewIntVar(0, len(days), "max_days")
    for e in inp.employees:
        if e.sunday_quota is None:
            sv = [worked[e.id, d] for d in suns_all if (e.id, d) in worked]
            if sv:
                m.Add(mx_sun >= sum(sv))
        dv = [worked[e.id, d] for d in days if (e.id, d) in worked]
        if dv:
            m.Add(mx_days >= sum(dv))
    terms["sunday_balance"].append(W["sunday_balance"] * mx_sun)
    terms["days_balance"].append(W["days_balance"] * mx_days)

    # Alternance matin / soir : pénalité quand deux jours consécutifs passent d'un extrême à l'autre
    for e in inp.employees:
        cat_vars: Dict[tuple, Dict[str, list]] = defaultdict(lambda: defaultdict(list))
        for s in by_emp[e.id]:
            c = prep.category[s.id]
            if c in ("matin", "soir"):
                cat_vars[s.day][c].append(x[e.id, s.id])
        for i, d in enumerate(days[:-1]):
            a, b = cat_vars.get(d), cat_vars.get(days[i + 1])
            if not a or not b:
                continue
            for c1, c2 in (("matin", "soir"), ("soir", "matin")):
                if a.get(c1) and b.get(c2):
                    v = m.NewBoolVar(f"alt_{e.id}_{d}_{c1}")
                    m.Add(v >= sum(a[c1]) + sum(b[c2]) - 1)
                    terms["alternation"].append(W["alternation"] * v)

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
    scaled = {k: (ex * W[k] if k in _UNIT_TERMS else ex) for k, ex in exprs.items()}

    current: Dict[str, Optional[cp_model.CpSolver]] = {"solver": None}
    stopped = {"v": False}
    if cancel is not None:
        def _watch():
            while not stopped["v"]:
                if cancel.wait(0.1):
                    if current["solver"] is not None:
                        current["solver"].StopSearch()
                    return
        threading.Thread(target=_watch, daemon=True).start()

    # Réutilise le planning existant comme point de départ (réoptimisation) : solution plus rapide et moins de changements inutiles
    for sid, eid in inp.previous.items():
        if (eid, sid) in x:
            m.AddHint(x[eid, sid], 1)
    # Résolution niveau par niveau : la solution du niveau précédent sert de point de départ et sa valeur est figée
    groups_lv = _level_groups(cfg, exprs, bool(inp.previous)) or [("pondere", [])]
    deadline = t0 + cfg.time_limit_s
    shares = {"couverture": 0.35, "engagements": 0.25}
    floor = 5.0  # le préchargement d'un grand modèle prend plusieurs secondes : un niveau a besoin d'un minimum de temps pour exister
    carry: List[str] = []  # critères d'un niveau resté sans solution : reportés au suivant, jamais oubliés
    levels: List[dict] = []
    solver: Optional[cp_model.CpSolver] = None  # dernier solveur ayant une solution
    status = cp_model.UNKNOWN
    proved = True
    for i, (name, keys) in enumerate(groups_lv):
        keys = [*keys, *carry]
        expr = sum(scaled[k] for k in keys)
        last = i == len(groups_lv) - 1
        remaining = max(0.05, deadline - _time.time())
        sv = cp_model.CpSolver()
        sv.parameters.max_time_in_seconds = remaining if last else min(remaining, max(floor, remaining * shares.get(name, 0.5)))
        sv.parameters.num_workers = cfg.workers
        sv.parameters.random_seed = cfg.seed
        current["solver"] = sv
        m.Minimize(expr)
        report(phase="level", level=name, index=i + 1, count=len(groups_lv), solutions=0)
        last_push = {"t": 0.0}

        def _seen(n: int, value: float, _name=name, _i=i) -> None:
            now = _time.time()
            if now - last_push["t"] >= 0.5:  # au plus deux mises à jour par seconde
                last_push["t"] = now
                report(phase="level", level=_name, index=_i + 1, count=len(groups_lv), solutions=n, best=int(value))
        st = sv.Solve(m, _StopAtZero(_seen) if keys else None)
        if st == cp_model.UNKNOWN and solver is None and not last and not (cancel is not None and cancel.is_set()) and deadline - _time.time() > 0.5:
            # ni solution ni preuve dans la part de ce niveau : il ne s'arrête pas là, il reçoit tout le temps restant (sinon « interrompu »
            # serait annoncé alors que le budget n'est pas épuisé ; les niveaux suivants n'ont de sens qu'avec une première solution)
            sv = cp_model.CpSolver()
            sv.parameters.max_time_in_seconds = max(0.05, deadline - _time.time())
            sv.parameters.num_workers = cfg.workers
            sv.parameters.random_seed = cfg.seed
            current["solver"] = sv
            st = sv.Solve(m, _StopAtZero(_seen) if keys else None)
        if st in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            value = int(sv.Value(expr)) if keys else 0
            # tous les coûts sont positifs ou nuls : atteindre 0 prouve l'optimum de ce niveau, sans attendre la preuve du solveur
            level_proved = st == cp_model.OPTIMAL or value == 0
            solver, status = sv, cp_model.OPTIMAL if (level_proved and proved) else cp_model.FEASIBLE
            proved = proved and level_proved
            levels.append({"level": name, "terms": keys, "value": value, "proved_optimal": level_proved,
                           "bound": 0 if value == 0 else int(sv.BestObjectiveBound()), "seconds": round(sv.WallTime(), 3)})
            if last or (cancel is not None and cancel.is_set()):
                break
            # niveau non prouvé (temps écoulé) : sa valeur n'est PAS une limite définitive ; ses critères restent optimisés au niveau
            # suivant (avec leur poids, donc toujours en priorité), sinon une couverture médiocre trouvée sous charge resterait figée
            carry = [] if level_proved else list(keys)
            m.Add(expr <= value)  # le niveau suivant ne peut pas dégrader celui-ci
            # solution complète (variables auxiliaires comprises) : le niveau suivant repart immédiatement de ce planning
            m.ClearHints()
            for idx in range(len(m.Proto().variables)):
                var = m.GetIntVarFromProtoIndex(idx)
                m.AddHint(var, sv.Value(var))
        elif solver is None:
            status, solver = st, sv
            break
        else:  # pas de solution à ce niveau dans le temps imparti : la solution précédente reste valable, le niveau suivant garde sa chance
            proved = False
            status = cp_model.FEASIBLE
            levels.append({"level": name, "terms": keys, "value": None, "proved_optimal": False, "bound": None, "seconds": round(sv.WallTime(), 3)})
            carry = keys
            if cancel is not None and cancel.is_set():
                break
    stopped["v"] = True
    dur = _time.time() - t0
    report(phase="checking")

    names = {cp_model.OPTIMAL: "optimal", cp_model.FEASIBLE: "faisable"}
    missing = missing_data(inp)
    possible = len(inp.employees) * len(inp.slots)
    base = dict(duration_s=round(dur, 3), weights=dict(W), missing_data=missing, levels=levels, proved_optimal=status == cp_model.OPTIMAL,
                model={"employees": len(inp.employees), "shifts": len(inp.slots), "possible_pairs": possible, "decision_variables": len(x), "filtered_out": possible - len(x)})
    exploratory = any(i.severity in ("blocking", "warning") and i.code in ("CONTRACT_MISSING",) for i in missing)
    mode = "simulation_exploratoire" if exploratory else "validable"

    if status in (cp_model.INFEASIBLE, cp_model.MODEL_INVALID) or status == cp_model.UNKNOWN:
        diag = []
        if status == cp_model.INFEASIBLE:
            diag = [_lock_issue(prep, sid, eid) for sid, eid in impossible_locks]
            diag += [core_issue(inp, solver, assump)] if assump else []
            if min_lits:  # minimums de jours qui, ensemble, rendent le problème impossible
                idx = set(solver.SufficientAssumptionsForInfeasibility())
                core = [k for k, lit in min_lits.items() if lit.Index() in idx]
                diag += [min_days_core_issue(prep, core)] if core else []
            elif not cfg.min_days_core and any(e.min_days_month for e in inp.employees):
                diag = _min_days_conflict(inp) + diag
            diag += diagnose_uncovered(inp, [s.id for s in inp.slots if s.mandatory], inp.locked)
            st_name = "infaisable"
        else:
            st_name = "interrompu"
            diag = []
        return SolverResult(status=st_name, mode=mode, validable=False, assignments=[], uncovered_slots=[],
                            budgets=[], objective={}, preferences={}, avoided_violations={},
                            hard_violations=[], employee_hours={}, diagnostics=diag, sunday=sunday_summary(inp), **base)

    assigns: List[Assignment] = []
    for (eid, sid), v in x.items():
        if solver.Value(v):
            s = slots[sid]
            h = s.hours
            assigns.append(Assignment(sid, eid, s.day, s.start, s.end, h.presence_minutes, h.break_minutes,
                                      h.effective_minutes, dict(s.allocations), locked=inp.locked.get(sid) == eid))
    assigns.sort(key=lambda a: (a.day, a.start, a.slot_id))
    if not assigns and status != cp_model.OPTIMAL and prep.eligible and not (cancel is not None and cancel.is_set()):
        # aucune affectation et aucune preuve alors que des affectations sont possibles : le temps a manqué (machine chargée ou délai
        # trop court). Un planning vide n'est jamais présenté comme « partiellement couvert ».
        diag = [Issue("TIME_LIMIT", "warning", "Temps de calcul insuffisant : aucune affectation n'a pu être trouvée dans le délai accordé. "
                      "Relancez la génération (délai plus long, ou machine moins chargée). Rien n'a été enregistré.",
                      suggestions=["Relancer avec un délai de calcul plus long."])]
        return SolverResult(status="interrompu", mode=mode, validable=False, assignments=[], uncovered_slots=[],
                            budgets=[], objective={}, preferences={}, avoided_violations={},
                            hard_violations=[], employee_hours={}, diagnostics=diag, sunday=sunday_summary(inp), **base)
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
    # coût réel par critère, recalculé sur les affectations (aucune variable auxiliaire du solveur n'intervient)
    true_cost = evaluate(inp, assigns, prep)
    objective = {k: true_cost.get(k, 0) for k in exprs}

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
    st_name = names.get(status, "faisable")
    if cancel is not None and cancel.is_set():
        st_name = "interrompu"
    elif uncovered or shortfall:
        st_name = "partiellement_couvert"
    diag = diagnose_uncovered(inp, uncovered, inp.locked) if uncovered else []
    avoided = {"conflits_chevauchement_repos": _count_conflict_pairs(inp, x)}
    return SolverResult(status=st_name, mode=mode, validable=(mode == "validable" and st_name in ("optimal", "faisable")
                                                              and not viol),
                        assignments=assigns, uncovered_slots=uncovered, budgets=budgets, objective=objective,
                        preferences=dict(prefs), avoided_violations=avoided, hard_violations=viol,
                        employee_hours=dict(hours), diagnostics=diag, sunday=sunday_summary(inp, assigns),
                        metrics=plan_metrics(inp, assigns, prep=prep), **base)


def _lock_issue(prep, sid: str, eid: str) -> Issue:
    """Un verrou impossible rend le problème infaisable : le diagnostic nomme le shift, la personne et la règle en cause."""
    s, e = prep.slots.get(sid), prep.emps.get(eid)
    if s is None or e is None:
        return Issue("LOCK_IMPOSSIBLE", "blocking", f"Verrou impossible sur {sid} : shift ou collaborateur absent des données du mois.", slots=[sid])
    why = ineligibility(e, s, prep.starts_by_site)
    return Issue("LOCK_IMPOSSIBLE", "blocking", f"Le shift verrouillé {sid} ({s.day}, {s.start:%H:%M}-{s.end:%H:%M}) ne peut pas rester à {e.name} : {why[1] if why else 'repos insuffisant avec une période voisine'}.",
                 slots=[sid], constraints=[why[0] if why else "REST"], suggestions=["Déverrouiller ce shift ou lever la contrainte, puis relancer la génération."])


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
                    ok = period_of(by_day_emp[e.id, d]) != period_of(o)
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


def _min_days_conflict(inp: SolverInput) -> List[Issue]:
    """Problème impossible alors que des minimums de jours sont posés : second calcul court, minimums en hypothèses, pour nommer ceux en cause."""
    import dataclasses
    cfg = dataclasses.replace(inp.config, min_days_core=True, hierarchical=False, time_limit_s=min(20.0, max(5.0, inp.config.time_limit_s / 2)))
    res = solve(dataclasses.replace(inp, config=cfg))
    return [i for i in res.diagnostics if i.code == "MIN_DAYS_CONFLICT"]
