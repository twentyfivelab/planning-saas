"""Sérialisation complète des données d'entrée du moteur (JSON) : sert à figer, dans chaque version d'un planning, le contexte exact
utilisé (collaborateurs, disponibilités, absences datées, besoins, budgets, règles, pondérations, verrous) et à le relire plus tard pour
vérifier la version avec SES règles, sans dépendre des données actuelles."""
from __future__ import annotations

from dataclasses import fields
from datetime import date, time
from typing import Any, Dict

from .model import BrandBudget, Contract, Employee, OutsideShift, Relation, Slot, SolverConfig, SolverInput

ENGINE_VERSION = "2026.11.17.2"  # à incrémenter à chaque changement de règle du moteur ou du vérificateur
FORMAT = 1

_SETS = {"skills", "unavailable_weekdays", "unavailable_dates", "forbidden_tags", "preferred_tags", "rest_weekdays_hard",
         "rest_weekdays_soft", "preferred_sites"}


def _j(v: Any) -> Any:
    if isinstance(v, (date, time)):
        return v.isoformat()
    if isinstance(v, (set, frozenset)):
        return sorted(_j(x) for x in v)
    if isinstance(v, (list, tuple)):
        return [_j(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _j(x) for k, x in v.items()}
    if hasattr(v, "__dataclass_fields__"):
        return {f.name: _j(getattr(v, f.name)) for f in fields(v)}
    return v


def input_to_dict(inp: SolverInput) -> Dict[str, Any]:
    out = {"format": FORMAT, "engine_version": ENGINE_VERSION, **_j(inp)}
    out["travel_minutes"] = sorted([a, b, v] for (a, b), v in inp.travel_minutes.items())  # clés composées : liste explicite
    return out


def _t(v):
    return None if v is None else time.fromisoformat(v)


def _d(v):
    return None if v is None else date.fromisoformat(v)


def _slot(d: dict) -> Slot:
    return Slot(d["id"], _d(d["day"]), d["site"], _t(d["start"]), _t(d["end"]), d["break_minutes"], dict(d["allocations"]), tag=d.get("tag", "day"),
                template_id=d.get("template_id", ""), required_skills=tuple(d.get("required_skills") or ()), mandatory=d.get("mandatory", True),
                day_group=d.get("day_group"), stagger_group=d.get("stagger_group"), priority=d.get("priority", 3), mission=d.get("mission"))


def _employee(d: dict) -> Employee:
    kw = {}
    names = {f.name for f in fields(Employee)}
    for k, v in d.items():
        if k not in names:
            continue  # champ d'un format futur : ignoré
        if k == "contract":
            v = None if v is None else Contract(**{f.name: v.get(f.name) for f in fields(Contract)})
        elif k == "relations":
            v = [Relation(r["kind"], r["other"], bool(r.get("strict")), r.get("scope", "site_day")) for r in v or []]
        elif k == "unavailable_dates":
            v = {_d(x) for x in v or []}
        elif k in _SETS:
            v = set(v or [])
        elif k in ("available_weekdays", "allowed_sites"):
            v = None if v is None else set(v)
        elif k in ("latest_start",):
            v = _t(v)
        elif k == "unavailable_windows":
            v = {(_d(a), _t(b), _t(c)) for a, b, c in v or []}
        elif k == "work_window":
            v = None if v is None else (_t(v[0]), _t(v[1]))
        elif k == "left_on":
            v = _d(v)
        elif k == "preferred_times":
            v = {(_t(a), _t(b)) for a, b in v or []}
        kw[k] = v
    return Employee(**kw)


def input_from_dict(d: Dict[str, Any]) -> SolverInput:
    c = d["config"]
    cfg = SolverConfig(**{f.name: c[f.name] for f in fields(SolverConfig) if f.name in c})
    cfg.break_rules = [tuple(x) for x in cfg.break_rules]
    return SolverInput(
        _d(d["period_start"]), _d(d["period_end"]), [_slot(s) for s in d["slots"]], [_employee(e) for e in d["employees"]],
        [BrandBudget(b["brand"], b["target_minutes"], b.get("requirements_defined", True), b.get("strict", True)) for b in d["budgets"]], cfg,
        locked=dict(d.get("locked") or {}), previous=dict(d.get("previous") or {}), leaves_provided=d.get("leaves_provided", False),
        hypotheses=list(d.get("hypotheses") or []),
        outside_shifts=[OutsideShift(o["employee_id"], _d(o["day"]), _t(o["start"]), _t(o["end"]), o.get("minutes", 0)) for o in d.get("outside_shifts") or []],
        history_provided=d.get("history_provided", False),
        site_starts={k: [_t(x) for x in v] for k, v in (d.get("site_starts") or {}).items()},
        allowed_times={k: [(_t(a), _t(b)) for a, b in v] for k, v in (d.get("allowed_times") or {}).items()},
        frozen_empty=set(d.get("frozen_empty") or []),
        travel_minutes={(a, b): int(v) for a, b, v in d.get("travel_minutes") or []})
