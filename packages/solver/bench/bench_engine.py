"""Mesures du moteur CP-SAT sur des instances synthétiques reproductibles (graine fixe) : temps jusqu'à la première solution valide,
statut, preuve d'optimalité par niveau, couverture, équité, mémoire. Usage : python bench/bench_engine.py [limite_s]"""
import json
import random
import resource
import sys
import time as _t
from datetime import date, time, timedelta

from planning_solver import solve
from planning_solver.model import PRIORITY, REINFORCE, SECONDARY, Contract, Employee, Slot, SolverConfig, SolverInput


def instance(n_emp: int, n_days: int = 30, seed: int = 42, limit: float = 30.0) -> SolverInput:
    rnd = random.Random(seed)
    days = [date(2027, 3, 1) + timedelta(days=k) for k in range(n_days)]
    n_sites = max(2, n_emp // 12)
    sites, brands = [f"S{i}" for i in range(n_sites)], [f"B{i}" for i in range(n_sites)]
    slots = []
    for i, st in enumerate(sites):
        for d in days:
            for h, tag in (((6, 0), "open"), ((10, 0), "day"), ((12, 0), "close")):
                for k in range(2):
                    slots.append(Slot(f"{st}-{h[0]}-{k}|{d}", d, st, time(*h), time(h[0] + 9, h[1]), 60, {brands[i]: 480}, tag=tag))
    es = []
    for i in range(n_emp):
        allowed = rnd.sample(brands, min(3, len(brands)))
        es.append(Employee(f"e{i:03d}", f"C{i}", {b: rnd.choice([PRIORITY, PRIORITY, SECONDARY, REINFORCE]) for b in allowed},
                           contract=Contract(monthly_target_minutes=rnd.choice([80, 120, 160]) * 60),
                           time_pref=rnd.choice([None, "matin", "soir"]), unavailable_dates=set(rnd.sample(days, 3)), weight=rnd.choice([0.75, 1, 1.25]),
                           min_days_month=rnd.choice([None, None, 8, 10]), max_days_month=rnd.choice([None, 20, 22])))
    return SolverInput(days[0], days[-1], slots, es, [], SolverConfig(time_limit_s=limit, workers=8, monthly_cap_minutes=176 * 60))


def run(n_emp: int, limit: float) -> dict:
    inp = instance(n_emp, limit=limit)
    events, t0 = [], _t.time()
    res = solve(inp, progress=lambda p: events.append((round(_t.time() - t0, 2), p)))
    first = next((t for t, p in events if p.get("phase") == "level" and p.get("solutions", 0) >= 1), None)
    mandatory = sum(1 for s in inp.slots if s.mandatory)
    return {"collaborateurs": n_emp, "shifts": len(inp.slots), "variables": res.model.get("decision_variables"), "statut": res.status,
            "optimalite_prouvee": res.proved_optimal, "premiere_solution_s": first, "duree_s": res.duration_s,
            "couverture_pct": round(100 * (mandatory - len(res.uncovered_slots)) / max(1, mandatory), 1),
            "niveaux": [(lv["level"], lv["value"], lv["proved_optimal"], lv["seconds"]) for lv in res.levels],
            "violations": len(res.hard_violations), "equite_ecart_moyen_h": (res.metrics.get("fairness") or {}).get("mean_abs_gap_hours"),
            "memoire_max_mo": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024 / 1024, 1)}


if __name__ == "__main__":
    limit = float(sys.argv[1]) if len(sys.argv) > 1 else 30.0
    for n in (30, 60, 100, 150):
        print(json.dumps(run(n, limit), ensure_ascii=False), flush=True)
