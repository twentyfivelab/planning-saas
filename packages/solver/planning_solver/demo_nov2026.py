"""Jeu de démonstration novembre 2026. Rien n'est inventé : les hypothèses sont listées et exposées."""
from __future__ import annotations

from datetime import date, time, timedelta
from typing import Dict, List, Optional

from .model import (BrandBudget, Employee, PRIORITY, REINFORCE, Slot, SolverConfig, SolverInput)
from .timecalc import shift_hours, split_allocation

START, END = date(2026, 11, 1), date(2026, 11, 30)
MON, TUE, WED, THU, FRI, SAT, SUN = range(7)

BUDGET_HOURS = {"Ploom GVA3": 720, "Ploom GVA9": 480, "Cartier": 64, "Valmont": 136, "Cellcosmet": 68,
                "Nuxe": 68, "Cailler": 88, "Lindt": 64, "Toblerone": 64}
TOTAL_HOURS = 1752

# Horaires NON FOURNIS par le client : valeurs supposées, paramétrables, NON VALIDÉES.
# Valmont (08-17, 09-18, 10-19) est fourni ; Nuxe/Cellcosmet et Cailler ne le sont pas.
VALMONT_TEMPLATES = [(time(8), time(17)), (time(9), time(18)), (time(10), time(19))]
ASSUMED_CN_TEMPLATES = [(time(8), time(17)), (time(9), time(18)), (time(10), time(19))]
ASSUMED_CAILLER_TEMPLATE = (time(9), time(18))
HYPOTHETICAL_TEMPLATES = {
    **{f"CN-{a:%H}": "Horaire Nuxe/Cellcosmet supposé (non fourni), non validé" for a, _ in ASSUMED_CN_TEMPLATES},
    "CAILLER-09": "Horaire Cailler supposé (non fourni), non validé",
}

HYPOTHESES = [
    "HYPOTHÈSE NON VALIDÉE — horaires Nuxe/Cellcosmet : mêmes modèles que Valmont (08-17, 09-18, 10-19), non fournis.",
    "HYPOTHÈSE NON VALIDÉE — horaire Cailler : 09:00-18:00 (1 h de pause), non fourni.",
    "HYPOTHÈSE NON VALIDÉE — collaborateurs sans marque indiquée (Mila, Abdu, Sabrina, Kristina, Florian, Simona D, Yasmine, Michael, "
    "Adam) : supposés éligibles Ploom uniquement ; Aziza : chocolat (Cailler, Lindt, Toblerone) uniquement.",
    "HYPOTHÈSE NON VALIDÉE — poids d'attribution : 1.25 pour Sahra, Mila, Abdu ; 0.75 pour Yasmine ; valeurs de paramétrage, pas des contrats.",
    "HYPOTHÈSE NON VALIDÉE — un seul collaborateur par shift (effectif requis = 1) ; aucun historique avant le 1er novembre.",
]


def _d(i: int) -> date:
    return START + timedelta(days=i)


def all_days() -> List[date]:
    return [_d(i) for i in range((END - START).days + 1)]


def _slot(sid, day, site, start, end, alloc_brands, tag="day", tpl="", mandatory=True, group=None, stagger=None,
          split: Optional[Dict[str, float]] = None) -> Slot:
    h = shift_hours(day, start, end, 60)
    shares = split or {b: 1 for b in alloc_brands}
    return Slot(sid, day, site, start, end, 60, split_allocation(h.effective_minutes, shares), tag=tpl and tag,
                template_id=tpl, mandatory=mandatory, day_group=group, stagger_group=stagger)


def build_slots(cn_split: Optional[Dict[str, float]] = None, cn_templates=None, cailler_template=None) -> List[Slot]:
    """cn_templates / cailler_template : horaires supposés, surchargeables (configurables)."""
    cn_split = cn_split or {"Cellcosmet": 1, "Nuxe": 1}
    cn_templates = cn_templates or ASSUMED_CN_TEMPLATES
    cailler_start, cailler_end = cailler_template or ASSUMED_CAILLER_TEMPLATE
    out: List[Slot] = []
    cos = VALMONT_TEMPLATES
    for d in all_days():
        k = d.isoformat()
        for st, en, tag, tpl in ((6, 15, "open", "GVA3-06"), (10, 19, "mid", "GVA3-10"),
                                 (12, 21, "close", "GVA3-12")):
            out.append(_slot(f"GVA3|{k}|{tpl}", d, "GVA3", time(st), time(en), ["Ploom GVA3"], tag, tpl))
        out.append(_slot(f"GVA9|{k}|GVA9-07", d, "GVA9", time(7), time(16), ["Ploom GVA9"], "open", "GVA9-07"))
        out.append(_slot(f"GVA9|{k}|GVA9-1230", d, "GVA9", time(12, 30), time(21, 30), ["Ploom GVA9"], "close",
                         "GVA9-1230"))
        if d.weekday() in (FRI, SAT):
            out.append(_slot(f"CARTIER|{k}", d, "Cartier", time(8), time(17), ["Cartier"], "day", "CARTIER-08"))
        if d.weekday() not in (TUE, SUN):
            for s, e in cos:
                out.append(_slot(f"VALMONT|{k}|{s:%H}", d, "Valmont", s, e, ["Valmont"], "day", f"VALMONT-{s:%H}",
                                 mandatory=False, group=f"VALMONT|{k}", stagger="COSMETIQUE"))
        if d.weekday() not in (WED, SUN):
            for s, e in cn_templates:
                out.append(_slot(f"CN|{k}|{s:%H}", d, "Nuxe/Cellcosmet", s, e, list(cn_split), "day",
                                 f"CN-{s:%H}", mandatory=False, group=f"CN|{k}", stagger="COSMETIQUE",
                                 split=cn_split))
        if d.weekday() != SUN:
            out.append(_slot(f"CAILLER|{k}", d, "Cailler", cailler_start, cailler_end, ["Cailler"], "day", "CAILLER-09",
                             mandatory=False, group=f"CAILLER|{k}"))
    return out


def build_employees() -> List[Employee]:
    P3, P9 = "Ploom GVA3", "Ploom GVA9"
    ploom = {P3: PRIORITY, P9: PRIORITY}
    cosm = {"Valmont": REINFORCE, "Cellcosmet": REINFORCE, "Nuxe": REINFORCE}
    E = Employee
    return [
        E("mila", "Mila", dict(ploom), weight=1.25, preferred_times={(time(6), time(15)), (time(7), time(16))},
          preferred_tags={"open"}, opposite_of="abdu"),
        E("abdu", "Abdu", dict(ploom), weight=1.25, opposite_of="mila"),
        E("sabrina", "Sabrina", dict(ploom), forbidden_tags={"close"}),
        E("kristina", "Kristina", dict(ploom), preferred_tags={"close"}, preference_strength=3),
        E("florian", "Florian", dict(ploom), preferred_tags={"close"}),
        E("sahra", "Sahra", {**ploom, "Cartier": PRIORITY, **cosm}, weight=1.25, latest_start=time(10)),
        E("zaki", "Zaki", {**ploom, "Cartier": PRIORITY, **cosm}, latest_start=time(10),
          weekly_rest_days_pref=3),
        E("simona", "Simona D", dict(ploom), preferred_times={(time(10), time(19))}),
        E("yasmine", "Yasmine", dict(ploom), available_weekdays={MON, TUE, WED}, weight=0.75),
        E("michael", "Michael", dict(ploom)),
        E("adam", "Adam", dict(ploom)),
        E("valerie", "Valérie", {"Cailler": PRIORITY, P3: REINFORCE, P9: REINFORCE, "Cartier": REINFORCE,
                                 "Lindt": REINFORCE, "Toblerone": REINFORCE}),
        E("pierre", "Pierre", {"Lindt": PRIORITY, "Toblerone": PRIORITY, "Cailler": REINFORCE,
                               P3: REINFORCE, P9: REINFORCE}),
        E("aziza", "Aziza", {"Cailler": PRIORITY, "Lindt": PRIORITY, "Toblerone": PRIORITY}),
        E("ying", "Ying", {"Valmont": PRIORITY, P3: REINFORCE, P9: REINFORCE}, max_days_per_week=3,
          preferred_times={(time(8), time(17)), (time(9), time(18))}),
        E("chloe", "Chloé", {"Valmont": PRIORITY, "Cartier": REINFORCE}, unavailable_weekdays={WED, SAT},
          preferred_times={(time(10), time(19))}),
        E("jane", "Jane", {"Cellcosmet": PRIORITY, "Nuxe": PRIORITY}, unavailable_weekdays={TUE}),
    ]


def build_input(cn_split: Optional[Dict[str, float]] = None, config: Optional[SolverConfig] = None,
                cn_templates=None, cailler_template=None) -> SolverInput:
    budgets = [BrandBudget(b, h * 60, requirements_defined=b not in ("Lindt", "Toblerone"))
               for b, h in BUDGET_HOURS.items()]
    return SolverInput(START, END, build_slots(cn_split, cn_templates, cailler_template), build_employees(), budgets,
                       config or SolverConfig(), hypotheses=list(HYPOTHESES))
