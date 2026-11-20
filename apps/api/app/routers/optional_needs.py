"""Besoins optionnels non attribués du mois : visibles et complétables à la main (le moteur n'en retient que ce que les budgets et
l'équilibre des heures justifient). Placer un besoin crée le shift sans collaborateur ; l'attribution passe ensuite par la fenêtre
habituelle (contrôles, confirmations, rappels). Aucune affectation n'est créée ici."""
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from planning_solver.timecalc import shift_hours

from .. import models as m
from ..deps import Ctx, audit, get_or_404, require
from ..period_state import ensure_editable
from ..services_bridge import build_input
from ..readcache import cached_view

router = APIRouter(tags=["besoins optionnels"])


@router.get("/periods/{pid}/optional-needs")
@cached_view("optional")
def optional_needs(pid: str, ctx: Ctx = Depends(require("planning.read"))):
    p = get_or_404(ctx, m.PlanningPeriod, pid)
    inp = build_input(ctx.db, p)
    shifts = {sh.slot_key: sh for sh in ctx.db.scalars(select(m.Shift).where(m.Shift.period_id == p.id))}
    taken = set(ctx.db.scalars(select(m.Assignment.shift_id).where(m.Assignment.period_id == p.id)))
    site_names = {x.code: x.name for x in ctx.db.scalars(select(m.Site))}
    brand_names = {b.code: b.name for b in ctx.db.scalars(select(m.Brand))}
    budgets = {b.brand: b for b in inp.budgets}
    planned = defaultdict(int)
    items, by_brand = [], defaultdict(lambda: {"shifts": 0, "minutes": 0})
    for s in inp.slots:
        sh = shifts.get(s.id)
        if sh is not None and sh.id in taken:
            for b, mi in s.allocations.items():
                planned[b] += mi
            continue
        if s.mandatory:
            continue  # un besoin obligatoire non couvert est déjà signalé dans le planning (shifts non couverts)
        key = tuple(sorted(s.brands))
        by_brand[key]["shifts"] += 1
        by_brand[key]["minutes"] += s.effective_minutes
        items.append({"slot_key": s.id, "day": s.day.isoformat(), "start": s.start.isoformat()[:5], "end": s.end.isoformat()[:5], "site": s.site,
                      "site_name": site_names.get(s.site, s.site), "brands": sorted(s.brands), "brand_label": " + ".join(brand_names.get(b, b) for b in key), "minutes": s.effective_minutes,
                      "shift_id": str(sh.id) if sh else None, "placed": sh is not None})
    items.sort(key=lambda x: (x["day"], x["start"], x["brand_label"]))
    brands = []
    for key, v in sorted(by_brand.items()):
        bud = [budgets[c] for c in key if c in budgets]
        brands.append({"brand": " + ".join(brand_names.get(c, c) for c in key), "codes": list(key), **v,
                       "budget_minutes": sum(b.target_minutes for b in bud) if bud else None, "planned_minutes": sum(planned.get(c, 0) for c in key)})
    return {"total": len(items), "minutes": sum(x["minutes"] for x in items), "brands": brands, "items": items}


class PlaceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slot_key: str = Field(min_length=1, max_length=200)


@router.post("/periods/{pid}/needs/place", status_code=201)
def place_need(pid: str, body: PlaceIn, ctx: Ctx = Depends(require("planning.edit"))):
    """Place un besoin du mois dans le planning (shift sans collaborateur). Jamais en double."""
    p = get_or_404(ctx, m.PlanningPeriod, pid)
    ensure_editable(ctx.db, p.id)
    s = next((x for x in build_input(ctx.db, p).slots if x.id == body.slot_key), None)
    if s is None:
        raise HTTPException(422, "Ce besoin n'existe pas (ou plus) ce mois-ci.")
    sh = ctx.db.scalar(select(m.Shift).where(m.Shift.period_id == p.id, m.Shift.slot_key == s.id))
    if sh is not None:
        return {"shift_id": str(sh.id), "day": sh.day.isoformat(), "already": True}
    h = shift_hours(s.day, s.start, s.end, s.break_minutes)
    sh = m.Shift(tenant_id=ctx.tenant_id, period_id=p.id, slot_key=s.id, day=s.day, site_code=s.site, start_time=s.start, end_time=s.end,
                 break_minutes=s.break_minutes, presence_minutes=h.presence_minutes, effective_minutes=h.effective_minutes)
    ctx.db.add(sh)
    ctx.db.flush()
    from ..history import shift_context
    audit(ctx, "need.placed", "shift", sh.id, {"period_id": str(p.id), "day": s.day.isoformat(), "start": s.start.isoformat(), "end": s.end.isoformat(),
                                                **shift_context(ctx.db, sh), "brands": sorted(s.brands), "optional": not s.mandatory})
    return {"shift_id": str(sh.id), "day": s.day.isoformat(), "already": False}
