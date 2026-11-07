"""Évaluateur indépendant de la fonction objectif : recalcule, SANS CP-SAT, le coût exact (par critère) d'un planning donné, avec les
mêmes règles et les mêmes poids que le moteur. Sert à vérifier le moteur (test : coût recalculé = coût du solveur à l'optimum), à
classer les remplaçants (coût marginal réel d'un changement) et à expliquer les affectations (contribution de chaque critère)."""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, Iterable, List, Optional, Tuple

from .context import (Prepared, cost_units, coverage_cost, hours_units, individual_penalty, period_of, prepare,
                      preference_checks, relation_pairs)
from .model import Assignment, DEFAULT_WEIGHTS, REINFORCE, SECONDARY, Slot, SolverInput


def _ceil_div(a: int, b: int) -> int:
    return -(-a // b)


class Evaluator:
    def __init__(self, inp: SolverInput, assignments: Iterable[Assignment], prep: Optional[Prepared] = None):
        self.inp = inp
        self.prep = prep or prepare(inp)
        self.W = {**DEFAULT_WEIGHTS, **inp.config.weights}
        self.holder: Dict[str, str] = {}
        self.mine: Dict[str, List[Slot]] = defaultdict(list)
        for a in assignments:
            s = self.prep.slots.get(a.slot_id)
            if s is not None:
                self.holder[a.slot_id] = a.employee_id
                self.mine[a.employee_id].append(s)
        self.weeks: Dict[tuple, list] = defaultdict(list)
        for d in self.prep.days:
            self.weeks[d.isocalendar()[:2]].append(d)
        self.rel_entries = self._relation_entries()
        self._emp_cache = {e.id: self.employee_terms(e.id, self.mine.get(e.id, [])) for e in inp.employees}
        self._rel_cache = [self._relation_cost(ent, self.mine) for ent in self.rel_entries]

    # --- coûts propres à un collaborateur ---
    def employee_terms(self, eid: str, lst: List[Slot]) -> Dict[str, int]:
        W, prep = self.W, self.prep
        e = prep.emps.get(eid)
        out: Dict[str, int] = defaultdict(int)
        if e is None:
            return out
        worked = {s.day for s in lst}
        tot = sum(s.effective_minutes for s in lst)
        options = prep.by_emp.get(eid, [])
        option_days = {s.day for s in options}
        if e.weekly_rest_days_pref is not None and not e.weekly_rest_days_hard:
            cap = 7 - e.weekly_rest_days_pref
            for wdays in self.weeks.values():
                if len(wdays) == 7 and (option_days & set(wdays)):
                    out["rest_days"] += W["rest_days"] * max(0, sum(1 for d in wdays if d in worked) - cap)
        if prep.suns and e.sunday_quota is not None and e.sunday_mode == "exact":
            cap = min(e.sunday_quota, len(prep.suns))
            if cap > 0 and any(d in option_days for d in prep.suns):
                out["sunday_quota"] += W["sunday_quota"] * max(0, cap - sum(1 for d in prep.suns if d in worked))
        c = e.contract
        if c and c.monthly_target_minutes is not None:
            out["overtime"] += W["overtime"] * max(0, _ceil_div(tot - c.monthly_target_minutes, 60))
        days = prep.days
        for i in range(len(days) - 4):
            if all(d in worked for d in days[i:i + 5]):
                out["fatigue"] += W["fatigue"]
        for s in lst:
            lv = [e.brands.get(b, REINFORCE) for b in s.brands]  # marque hors fiche (dérogation) : au coût du renfort
            unit = W["reinforce"] if REINFORCE in lv else (W["secondary"] if SECONDARY in lv else 0)
            out["reinforce"] += unit * hours_units(s)
            out["cost"] += W["cost"] * cost_units(e, s)
            for _code, ok, force in preference_checks(e, s):
                if not ok:
                    out["preference"] += W["preference"] * force
            if e.time_pref and not e.time_pref_strict:
                cat = prep.category[s.id]
                if cat is not None and cat != e.time_pref:
                    out["time_pref"] += W["time_pref"] * max(1, e.preference_strength)
            out["individual"] += W["individual"] * individual_penalty(prep, e) * hours_units(s)
        if options:
            out["fairness"] += W["fairness"] * _ceil_div(abs(tot - prep.targets[eid]), 30)
        by_day: Dict[object, List[Slot]] = defaultdict(list)
        for s in lst:
            by_day[s.day].append(s)
        for i, d in enumerate(days[:-1]):
            today, tomorrow = by_day.get(d), by_day.get(days[i + 1])
            if not today or not tomorrow:
                continue
            next_sites = {s.site for s in tomorrow}
            for st in {s.site for s in today}:
                if st not in next_sites:
                    out["site_change"] += W["site_change"]
            cats_t = {prep.category[s.id] for s in today}
            cats_n = {prep.category[s.id] for s in tomorrow}
            for c1, c2 in (("matin", "soir"), ("soir", "matin")):
                if c1 in cats_t and c2 in cats_n:
                    out["alternation"] += W["alternation"]
        return out

    # --- coûts entre collaborateurs (horaires opposés, relations) ---
    def _relation_entries(self) -> List[Tuple[str, str, List[str], bool]]:
        out = []
        for e in self.inp.employees:
            if e.opposite_of and e.opposite_of in self.prep.emps and e.id < e.opposite_of:
                out.append(("opposite", e.id, [e.opposite_of], False))
        for kind, e, others, strict in relation_pairs(self.prep):
            out.append((kind, e.id, others, strict))
        return out

    def _relation_cost(self, entry, mine: Dict[str, List[Slot]]) -> int:
        kind, eid, others, strict = entry
        w = self.W["family"]
        if strict or not w:
            return 0
        if kind == "opposite":
            a = {(s.day, period_of(s)) for s in mine.get(eid, [])}
            b = {(s.day, period_of(s)) for s in mine.get(others[0], [])}
            return w * len(a & b)
        a = {(s.day, s.site) for s in mine.get(eid, [])}
        b = {(s.day, s.site) for o in others for s in mine.get(o, [])}
        if kind == "avoid_together":
            return w * len(a & b)
        if kind == "mentor":
            return w * len(a - b)
        return w * (len(a - b) + len(b - a))  # work_together : présent sans son binôme, dans les deux sens

    # --- coûts liés aux shifts eux-mêmes ---
    def _coverage(self, filled) -> int:
        if self.inp.config.strict_coverage:
            return 0
        return sum(coverage_cost(self.W["coverage"], s) for s in self.inp.slots if s.mandatory and s.id not in filled)

    def _budget_terms(self, filled) -> Dict[str, int]:
        out: Dict[str, int] = defaultdict(int)
        planned: Dict[str, int] = defaultdict(int)
        for sid in filled:
            for b, mi in self.prep.slots[sid].allocations.items():
                planned[b] += mi
        for b in self.inp.budgets:
            if not b.strict:
                out["budget_over"] += self.W["budget_over"] * max(0, _ceil_div(planned[b.brand] - b.target_minutes, 60))
            if b.brand in self.prep.optional_brands:
                out["budget"] += self.W["budget"] * max(0, _ceil_div(b.target_minutes - planned[b.brand], 60))
        return out

    def _stagger(self, filled) -> int:
        w, total = self.W["stagger"], 0
        groups: Dict[tuple, List[Slot]] = defaultdict(list)
        for sid in filled:
            s = self.prep.slots[sid]
            if s.stagger_group:
                groups[s.stagger_group, s.day].append(s)
        for ss in groups.values():
            for i, a in enumerate(ss):
                for b in ss[i + 1:]:
                    if a.brands != b.brands and abs((a.bounds[0] - b.bounds[0]).total_seconds()) / 60 < self.inp.config.stagger_minutes:
                        total += w
        return total

    def _stability(self, holder: Dict[str, str]) -> int:
        w, total = self.W["stability"], 0
        for sid, eid in self.inp.previous.items():
            if sid in self.inp.locked:
                continue
            if (eid, sid) in self.prep.eligible:
                total += 0 if holder.get(sid) == eid else w
            elif sid in self.prep.slots:
                total += w
        return total

    def _maxima(self, mine: Dict[str, List[Slot]]) -> Dict[str, int]:
        prep, W = self.prep, self.W
        m_open = m_close = m_we = m_sun = m_days = 0
        for e in self.inp.employees:
            lst = mine.get(e.id, [])
            m_open = max(m_open, sum(1 for s in lst if s.tag == "open"))
            m_close = max(m_close, sum(1 for s in lst if s.tag == "close"))
            m_we = max(m_we, sum(1 for s in lst if s.day.weekday() >= 5))
            days = {s.day for s in lst}
            m_days = max(m_days, len(days))
            if e.sunday_quota is None:
                m_sun = max(m_sun, sum(1 for d in prep.suns if d in days))
        return {"balance": W["balance"] * (m_open + m_close + m_we), "sunday_balance": W["sunday_balance"] * m_sun,
                "days_balance": W["days_balance"] * m_days}

    # --- totaux ---
    def _assemble(self, emp_terms: Iterable[Dict[str, int]], rel_costs: Iterable[int], holder: Dict[str, str], mine: Dict[str, List[Slot]]) -> Dict[str, int]:
        out: Dict[str, int] = defaultdict(int)
        for t in emp_terms:
            for k, v in t.items():
                out[k] += v
        out["family"] += sum(rel_costs)
        filled = set(holder)
        out["coverage"] += self._coverage(filled)
        for k, v in self._budget_terms(filled).items():
            out[k] += v
        out["stagger"] += self._stagger(filled)
        out["stability"] += self._stability(holder)
        for k, v in self._maxima(mine).items():
            out[k] += v
        return {k: int(v) for k, v in out.items()}

    def terms(self) -> Dict[str, int]:
        """Coût (déjà pondéré) par critère du planning, avec les mêmes clés que `SolverResult.objective`."""
        return self._assemble(self._emp_cache.values(), self._rel_cache, self.holder, self.mine)

    def total(self) -> int:
        return sum(self.terms().values())

    def terms_after(self, slot_id: str, new_emp: Optional[str]) -> Dict[str, int]:
        """Coût par critère si le shift `slot_id` passe à `new_emp` (None = laissé non couvert), sans modifier l'état."""
        s = self.prep.slots[slot_id]
        old = self.holder.get(slot_id)
        holder = dict(self.holder)
        mine = dict(self.mine)
        changed = {}
        if old is not None:
            mine[old] = [x for x in mine.get(old, []) if x.id != slot_id]
            changed[old] = self.employee_terms(old, mine[old])
            holder.pop(slot_id, None)
        if new_emp is not None:
            mine[new_emp] = [*mine.get(new_emp, []), s]
            changed[new_emp] = self.employee_terms(new_emp, mine[new_emp])
            holder[slot_id] = new_emp
        emp_terms = [changed.get(eid, t) for eid, t in self._emp_cache.items()]
        emp_terms += [t for eid, t in changed.items() if eid not in self._emp_cache]
        rel = [self._relation_cost(ent, mine) if ({ent[1], *ent[2]} & set(changed)) else self._rel_cache[i]
               for i, ent in enumerate(self.rel_entries)]
        return self._assemble(emp_terms, rel, holder, mine)

    def delta(self, slot_id: str, new_emp: Optional[str]) -> Dict[str, int]:
        """Variation de coût par critère (seuls les critères qui changent) si le shift change de titulaire."""
        before, after = self.terms(), self.terms_after(slot_id, new_emp)
        return {k: after.get(k, 0) - before.get(k, 0) for k in set(before) | set(after) if after.get(k, 0) != before.get(k, 0)}


def evaluate(inp: SolverInput, assignments: Iterable[Assignment], prep: Optional[Prepared] = None) -> Dict[str, int]:
    return Evaluator(inp, assignments, prep).terms()
