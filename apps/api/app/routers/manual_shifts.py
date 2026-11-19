"""Gestion manuelle des shifts depuis le calendrier : liste des shifts d'un jour, attribution / transfert avec vérification
des contraintes (dérogation possible pour un administrateur, sauf règles non dérogeables) et historique des modifications."""
import copy
import dataclasses
import re
import uuid
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from planning_solver.model import Assignment as SAssign
from planning_solver.validator import validate

from .. import models as m
from ..approval import OVERRIDE_ROLES, override_refusal
from ..deps import Ctx, audit, get_or_404, require
from ..history import assignment_detail
from ..period_state import ensure_editable
from .. import regularize
from ..limits import guard_monthly_cap, month_minutes
from ..optimize import ensure_frozen
from ..services_bridge import assignments_for_validation, build_input
from .planning import _conflicts

router = APIRouter(tags=["gestion manuelle des shifts"])

DAYS_FR = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]

LABELS = {
    "UNAVAILABLE": "Collaborateur indisponible ce jour-là",
    "REST": "Repos quotidien inférieur au minimum",
    "CONSECUTIVE": "Trop de jours consécutifs travaillés",
    "MAX_DAYS_WEEK": "Nombre maximum de jours par semaine dépassé",
    "MAX_DAYS_MONTH": "Nombre maximum de jours sur la période dépassé",
    "SUNDAY_QUOTA": "Quota de dimanches dépassé",
    "TIME_PREF_STRICT": "Préférence horaire obligatoire non respectée",
    "SCHEDULE_NOT_ALLOWED": "Horaire hors des horaires autorisés de la boutique",
    "SKILL_MISSING": "Qualification manquante",
    "FORBIDDEN_TAG": "Type de shift interdit pour ce collaborateur",
    "CONTRACT_WEEKLY_MAX": "Maximum hebdomadaire du contrat dépassé",
    "CONTRACT_MONTHLY_MAX": "Maximum mensuel du contrat dépassé",
    "REST_DAYS_HARD": "Jours de repos hebdomadaires obligatoires non respectés",
    "BUDGET_EXCEEDED": "Budget horaire de la marque dépassé",
    "DAY_GROUP": "Le même groupe de jours est déjà pourvu",
    "EXCLUDED_FROM_PERIOD": "Collaborateur hors de l'effectif du mois",
    "REST_WEEKDAY": "Jour de repos obligatoire du collaborateur",
    "SITE_NOT_ALLOWED": "Site non autorisé pour ce collaborateur",
    "RELATION_AVOID": "Ces deux collaborateurs ne doivent pas travailler ensemble",
    "MENTOR_MISSING": "Un tuteur doit être présent le même jour sur ce site",
    "LEGAL_WEEKLY_MAX": "Durée maximale hebdomadaire du régime applicable dépassée",
    "BREAK_TOO_SHORT": "Pause inférieure au référentiel juridique",
    "MONTHLY_CAP": "Plafond mensuel d'heures dépassé",
    "MIN_DAYS_NOT_MET": "Nombre minimum de jours par mois non atteint",
    "EMPLOYEE_REMOVED": "Collaborateur supprimé de l'équipe",
    "UNAVAILABLE_PARTIAL": "Collaborateur absent pendant une partie de ce shift",
    "WORK_WINDOW": "Shift hors des horaires obligatoires du collaborateur",
    "TRAVEL_TIME": "Temps de déplacement entre les deux sites insuffisant",
}
LEGAL = {"REST", "CONSECUTIVE", "CONTRACT_WEEKLY_MAX", "CONTRACT_MONTHLY_MAX", "REST_DAYS_HARD", "LEGAL_WEEKLY_MAX", "BREAK_TOO_SHORT"}
# Une règle paramétrée « derogable: false » dans les règles de l'entreprise reste bloquante (aucune valeur légale n'est inventée ici).
RULE_CODES = {"rest_hours": "REST", "max_consecutive_days": "CONSECUTIVE", "weekly_max_minutes": "LEGAL_WEEKLY_MAX", "break_rules": "BREAK_TOO_SHORT"}


def _non_derogable(ctx: Ctx) -> set:
    out = set()
    for c in ctx.db.scalars(select(m.ConstraintDefinition).where(m.ConstraintDefinition.enabled.is_(True))):
        if c.code in RULE_CODES and (c.params or {}).get("derogable") is False:
            out.add(RULE_CODES[c.code])
    return out


def _fmt_slot(day: date, start, end) -> str:
    return f"{DAYS_FR[day.weekday()]} {day:%d/%m} {start:%Hh%M}–{end:%Hh%M}"


def _issue(code: str, level: str, message: str, **extra) -> dict:
    return {"code": code, "level": level, "message": message, "legal": code in LEGAL, **extra}


class Pre:
    """Contexte du moteur calculé UNE fois (liste du jour : une vérification par shift sans reconstruire le problème)."""

    def __init__(self, ctx: Ctx, p: m.PlanningPeriod):
        self.inp = build_input(ctx.db, p, {"cap": "current"})  # le plafond mensuel actuel s'applique à toute modification manuelle
        self.base = assignments_for_validation(ctx.db, self.inp, p)  # recale aussi les horaires modifiés à la main
        self.before = set(validate(self.inp, self.base))
        self.slots = {s.id: s for s in self.inp.slots}
        self.texts = {sid: _fmt_slot(s.day, s.start, s.end) for sid, s in self.slots.items()}
        self.ids = sorted(self.texts, key=len, reverse=True)
        self.nd = _non_derogable(ctx)
        self.minutes_before: dict = {}
        for a in self.base:
            self.minutes_before[a.employee_id] = self.minutes_before.get(a.employee_id, 0) + a.effective_minutes


def _worked_days(pre: Pre, code: str, slot_id: str, extra_day: Optional[date] = None) -> set:
    days = {a.day for a in pre.base if a.employee_id == code and a.slot_id != slot_id}
    days |= {o.day for o in pre.inp.outside_shifts if o.employee_id == code}
    if extra_day:
        days.add(extra_day)
    return days


def _rest_gap_hours(pre: Pre, code: str, slot) -> Optional[float]:
    from planning_solver.timecalc import shift_bounds
    b0, b1 = slot.bounds
    best = None
    others = [shift_bounds(a.day, a.start, a.end) for a in pre.base if a.employee_id == code and a.slot_id != slot.id]
    others += [shift_bounds(o.day, o.start, o.end) for o in pre.inp.outside_shifts if o.employee_id == code]
    for o0, o1 in others:
        gap = (b0 - o1).total_seconds() / 3600 if b0 >= o1 else (o0 - b1).total_seconds() / 3600 if o0 >= b1 else 0.0
        if best is None or gap < best:
            best = gap
    return best


def _issues(ctx: Ctx, p: m.PlanningPeriod, e: m.Employee, sh: m.Shift, current: Optional[m.Assignment], pre: Optional[Pre] = None, *,
            slot=None, moves: Optional[dict] = None, released: tuple = ()) -> list:
    """Alertes si `e` prend le shift `sh`. level = blocking (jamais dérogeable) | override (dérogation d'administration) | soft
    (préférence : confirmation simple). Chaque alerte précise la règle, la valeur autorisée, la valeur atteinte et la conséquence.
    Le MÊME contrôle sert aux opérations composées : `slot` = shift pas encore enregistré (duplication), `moves` = autres changements
    simultanés {slot_id: code collaborateur} (échange réciproque), `released` = shifts que `e` libère dans la même opération."""
    out: list = []
    if not e.active:
        return [_issue("INACTIVE", "blocking", f"{e.name} est inactif·ve.", rule="Collaborateur actif")]
    if e.deleted_at is not None:
        return [_issue("EMPLOYEE_REMOVED", "blocking", f"{e.name} a été supprimé·e de l'équipe : plus aucun shift ne peut lui être attribué (réintégrez-le d'abord).",
                       rule="Collaborateur supprimé")]
    if current is not None and current.employee_id == e.id:
        return [_issue("ALREADY_MINE", "blocking", f"Ce shift est déjà attribué à {e.name}.", rule="Un seul titulaire par shift")]
    day = slot.day if slot is not None else sh.day
    other = ctx.db.execute(select(m.Shift).join(m.Assignment, m.Assignment.shift_id == m.Shift.id)
                           .where(m.Assignment.employee_id == e.id, m.Shift.day == day, m.Shift.id.not_in([sh.id, *released]))).scalars().first()
    if other is not None:
        out.append(_issue("SAME_DAY", "override", f"{e.name} est déjà affecté·e ce jour-là ({other.site_code} {other.start_time:%Hh%M}–{other.end_time:%Hh%M}). "
                          "En confirmant, la nouvelle affectation est enregistrée provisoirement et un rappel « À régulariser » vous demandera "
                          "de traiter l'affectation initiale.", rule="Un seul shift par jour",
                          limit="1 shift", reached="2 shifts",
                          consequence="Double affectation provisoire : conflit à corriger avant toute validation ou publication."))
    pre = pre or Pre(ctx, p)
    if moves:  # changements simultanés appliqués au planning de référence (les valeurs « atteintes » en tiennent compte)
        pre = copy.copy(pre)
        pre.base = [dataclasses.replace(a, employee_id=moves[a.slot_id]) if a.slot_id in moves else a for a in pre.base]
    inp, base = pre.inp, pre.base
    if slot is not None:  # shift pas encore enregistré : ajouté au problème, optionnel (aucun manque de couverture créé)
        inp = dataclasses.replace(inp, slots=[*inp.slots, slot])
    slot = slot if slot is not None else pre.slots.get(sh.slot_key)
    if slot is None:
        raise HTTPException(422, "Ce shift n'est pas connu du moteur : régénérez le planning.")
    missing = sorted(b for b in slot.allocations if b not in (e.brands or {}))
    if missing:
        out.append(_issue("BRAND_NOT_AUTHORIZED", "override", f"{', '.join(missing)} n'est pas dans les marques autorisées de {e.name} (fiche collaborateur).",
                          rule="Marques et boutiques autorisées", limit=", ".join(sorted(e.brands or {})) or "aucune", reached=", ".join(missing),
                          consequence=f"{e.name} travaillerait sur une marque non autorisée dans sa fiche."))
    h = slot.hours
    hypo = [a for a in base if a.slot_id != slot.id] + [SAssign(slot.id, e.code, slot.day, slot.start, slot.end, h.presence_minutes, h.break_minutes,
                                                                 h.effective_minutes, dict(slot.allocations), True)]
    seen = set()
    for v in validate(inp, hypo):
        if v in pre.before:
            continue
        code = re.match(r"[A-Z_]+", v).group(0)
        holder = ctx.db.get(m.Employee, current.employee_id) if current is not None else None
        if code == "MIN_DAYS_NOT_MET" and holder is not None and holder.name in v:  # le titulaire actuel passerait sous son minimum
            got, need = re.search(r"(\d+)<(\d+)", v).groups()
            out.append(_issue(code, "override", f"{holder.name} passerait sous son minimum de {need} jours dans le mois ({got} jours).",
                              rule="Nombre minimum de jours par mois", limit=f"{need} jours", reached=f"{got} jours",
                              consequence=f"{holder.name} ne travaillerait plus assez de jours ce mois-ci."))
            continue
        if code in ("LOCK_VIOLATED", "BRAND_NOT_ELIGIBLE", "OVERLAP", "DOUBLE_ASSIGNMENT", "HOURS_MISMATCH", "ALLOCATION_MISMATCH") or (code not in ("BUDGET_EXCEEDED", "BREAK_TOO_SHORT") and e.name not in v):
            continue
        detail = v.split(": ", 1)[1] if ": " in v else ""
        for sid in pre.ids:
            detail = detail.replace(sid, pre.texts[sid])
        detail = detail.replace(e.name, "").strip()
        label = LABELS.get(code, code)
        nums = re.search(r"(\d+)>(\d+)", v)
        extra: dict = {"rule": label}
        if code == "REST":
            label = f"Repos quotidien inférieur à {inp.config.rest_hours} h"
            gap = _rest_gap_hours(pre, e.code, slot)
            extra = {"rule": "Repos quotidien minimum", "limit": f"{inp.config.rest_hours} h", "reached": f"{gap:.1f} h".replace(".0", "") if gap is not None else "—",
                     "consequence": f"{e.name} aurait moins de {inp.config.rest_hours} h de repos entre deux shifts."}
        elif code == "CONSECUTIVE":
            label = f"Plus de {inp.config.max_consecutive_days} jours consécutifs travaillés"
            days = sorted(_worked_days(pre, e.code, slot.id, slot.day))
            run, best, prev = 0, 0, None
            for d in days:
                run = run + 1 if prev is not None and (d - prev).days == 1 else 1
                best, prev = max(best, run), d
            extra = {"rule": "Jours consécutifs maximum", "limit": f"{inp.config.max_consecutive_days} jours", "reached": f"{best} jours",
                     "consequence": f"{e.name} travaillerait {best} jours d'affilée."}
        elif code == "MONTHLY_CAP" and nums:
            from planning_solver.model import fmt_minutes
            got, cap = int(nums.group(1)), int(nums.group(2))
            if pre.minutes_before.get(e.code, 0) >= got:
                continue  # heures inchangées ou en baisse : jamais un nouveau dépassement
            label = f"Plafond mensuel de {fmt_minutes(cap)} dépassé"
            extra = {"rule": "Plafond mensuel d'heures (règle de l'entreprise, tous sites et marques cumulés)", "limit": fmt_minutes(cap), "reached": fmt_minutes(got),
                     "consequence": f"{e.name} travaillerait {fmt_minutes(got)} dans le mois : affectation impossible."}
            detail = ""
        elif code == "MIN_DAYS_NOT_MET":
            continue  # minimum d'un autre collaborateur : sans lien avec cette affectation
        elif code in ("MAX_DAYS_WEEK", "MAX_DAYS_MONTH", "SUNDAY_QUOTA") and nums:
            unit = {"MAX_DAYS_WEEK": "jours dans la semaine", "MAX_DAYS_MONTH": "jours dans le mois", "SUNDAY_QUOTA": "dimanche(s)"}[code]
            extra = {"rule": label, "limit": f"{nums.group(2)} {unit}", "reached": f"{nums.group(1)} {unit}",
                     "consequence": f"{e.name} dépasserait son maximum de {int(nums.group(1)) - int(nums.group(2))} en plus."}
        elif code == "BUDGET_EXCEEDED" and nums:
            extra = {"rule": label, "limit": f"{int(nums.group(2)) / 60:g} h", "reached": f"{int(nums.group(1)) / 60:g} h",
                     "consequence": "Le budget horaire de la marque serait dépassé."}
        if (code, v) in seen:
            continue
        seen.add((code, v))
        # exclu du mois : le réintégrer d'abord ; plafond mensuel et collaborateur supprimé : jamais dérogeables
        level = "blocking" if code in pre.nd or code in ("EXCLUDED_FROM_PERIOD", "MONTHLY_CAP", "EMPLOYEE_REMOVED") else "override"
        if code == "UNAVAILABLE":
            out.append(_issue(code, level, f"{e.name} est indisponible le {DAYS_FR[slot.day.weekday()]} {slot.day:%d/%m}.", rule="Disponibilité du collaborateur",
                              limit="disponible", reached="indisponible ce jour", consequence=f"{e.name} serait planifié·e un jour d'indisponibilité."))
            continue
        out.append(_issue(code, level, f"{label} pour {e.name}" + (f" — {detail}." if detail else "."), **extra))
    if e.time_pref and not e.time_pref_strict:  # préférence souple : information, jamais un blocage
        from planning_solver.model import site_start_times, slot_category
        cat = slot_category(slot, site_start_times(inp))
        if cat is not None and cat != e.time_pref:
            out.append(_issue("TIME_PREF", "soft", f"{e.name} préfère les shifts de type « {e.time_pref} » ; ce shift est de type « {cat} ».", rule="Préférence horaire (souple)",
                              limit=f"préférence {e.time_pref}", reached=f"shift {cat}", consequence="Préférence non respectée : l'affectation reste possible."))
    if current is not None and current.locked:
        who = ctx.db.get(m.Employee, current.employee_id)
        out.append(_issue("LOCKED", "override", f"Ce shift est verrouillé{f' pour {who.name}' if who else ''} : sa modification demande une autorisation d'administration.",
                          needs_unlock=True, rule="Verrouillage", limit="shift verrouillé", reached="modification demandée", consequence="Le verrou serait remplacé par une nouvelle affectation manuelle verrouillée."))
    return out


class ManualIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    employee_id: uuid.UUID
    shift_id: uuid.UUID
    force: bool = False
    reason: Optional[str] = Field(None, max_length=300)
    expected_from: Optional[str] = Field(None, max_length=64)  # "free" ou id du titulaire affiché : détecte une modification concurrente


def _view(ctx: Ctx, pid, day: date):
    return ctx.db.scalars(select(m.Shift).where(m.Shift.period_id == pid, m.Shift.day == day).order_by(m.Shift.site_code, m.Shift.start_time, m.Shift.slot_key))


@router.get("/periods/{pid}/day-shifts")
def day_shifts(pid: str, day: date, employee_id: Optional[uuid.UUID] = None, ctx: Ctx = Depends(require("planning.read"))):
    """Tous les shifts d'une journée (toutes marques et boutiques), avec leur statut, le collaborateur affecté et les alertes de compatibilité."""
    p = get_or_404(ctx, m.PlanningPeriod, pid)
    pre = Pre(ctx, p)
    slots = pre.slots
    emps = {e.id: e for e in ctx.db.scalars(select(m.Employee))}
    target = emps.get(employee_id) if employee_id else None
    site_names = {x.code: x.name for x in ctx.db.scalars(select(m.Site))}
    asg = {a.shift_id: a for a in ctx.db.scalars(select(m.Assignment).where(m.Assignment.period_id == p.id))}
    allocs: dict = {}
    for b in ctx.db.scalars(select(m.BrandAllocation)):
        allocs.setdefault(b.assignment_id, {})[b.brand_code] = b.minutes
    rows = []
    for sh in _view(ctx, p.id, day):
        a = asg.get(sh.id)
        brands = sorted(allocs.get(a.id, {})) if a else sorted(slots[sh.slot_key].allocations) if sh.slot_key in slots else []
        who = emps.get(a.employee_id) if a else None
        issues = [] if target is None or (a and a.employee_id == target.id) else _issues(ctx, p, target, sh, a, pre)
        rows.append({"shift_id": str(sh.id), "assignment_id": str(a.id) if a else None, "slot_key": sh.slot_key, "site": site_names.get(sh.site_code, sh.site_code), "site_code": sh.site_code,
                     "start": sh.start_time.isoformat(), "end": sh.end_time.isoformat(), "effective_minutes": sh.effective_minutes,
                     "brands": brands, "status": "assigned" if a else "available", "locked": bool(a and a.locked), "manual": sh.slot_key.startswith("MANUAL|"),
                     "assigned_to": {"id": str(who.id), "name": who.name} if who else None,
                     "mine": bool(target and a and a.employee_id == target.id),
                     "brand_ok": all(b in (target.brands or {}) for b in brands) if target else True,
                     "issues": [{k: i.get(k) for k in ("code", "level", "message")} for i in issues]})
    mine = next((r for r in rows if r["mine"]), None)
    return {"day": day.isoformat(), "employee": {"id": str(target.id), "name": target.name} if target else None, "shifts": rows,
            "employee_has_shift": mine, "can_override": ctx.user.role in OVERRIDE_ROLES}


@router.post("/periods/{pid}/manual-assign")
def manual_assign(pid: str, body: ManualIn, ctx: Ctx = Depends(require("planning.edit"))):
    """Attribue un shift libre ou transfère un shift occupé, en UNE transaction (tout ou rien) : le titulaire change, aucun shift n'est
    créé ni dupliqué. Sans `force`, rien n'est modifié si une alerte existe (409 avec la liste). Les alertes bloquantes ne sont jamais
    dérogeables ; les autres demandent `force` (rôle d'administration, sauf simples préférences) ; la dérogation est tracée."""
    p = get_or_404(ctx, m.PlanningPeriod, pid)
    ensure_editable(ctx.db, p.id)
    sh = ctx.db.execute(select(m.Shift).where(m.Shift.id == body.shift_id, m.Shift.period_id == p.id).with_for_update()).scalar_one_or_none()
    if sh is None:
        raise HTTPException(404, "Introuvable")
    e = ctx.db.execute(select(m.Employee).where(m.Employee.id == body.employee_id).with_for_update()).scalar_one_or_none()
    if e is None:
        raise HTTPException(404, "Introuvable")
    current = ctx.db.scalar(select(m.Assignment).where(m.Assignment.shift_id == sh.id))
    if current is not None and current.employee_id == e.id and body.expected_from is not None and body.expected_from != str(e.id):
        # déjà fait par ce même envoi (double clic, nouvel essai après une coupure) : même résultat, rien n'est refait
        return {"assignment_id": str(current.id), "kind": "already", "already": True, "forced": False, "conflicts": _conflicts(ctx, p.id), "regularizations": []}
    if body.expected_from is not None and body.expected_from != (str(current.employee_id) if current else "free"):
        raise HTTPException(409, detail={"code": "stale", "can_override": False, "issues": [],
                                         "message": "Ce shift vient d'être modifié par quelqu'un d'autre. La liste a été actualisée : vérifiez puis recommencez."})
    issues = _issues(ctx, p, e, sh, current)
    refusal = override_refusal(ctx, (e.id, current.employee_id if current else None))
    can_override = refusal is None
    if any(i["level"] == "blocking" for i in issues):
        raise HTTPException(409, detail={"code": "blocked", "issues": issues, "can_override": False,
                                         "message": "Cette affectation est impossible : une règle non dérogeable est en cause."})
    if issues and not body.force:
        raise HTTPException(409, detail={"code": "needs_confirmation", "issues": issues, "can_override": can_override, "refusal": refusal,
                                         "message": "Des contraintes ne sont pas respectées. Confirmez pour déroger, ou annulez."})
    if issues and not can_override:
        raise HTTPException(403, detail={"code": "forbidden", "issues": issues, "can_override": False, "message": refusal})
    from_emp = ctx.db.get(m.Employee, current.employee_id) if current else None
    before_minutes = month_minutes(ctx.db, [e.id], [(sh.day.year, sh.day.month)])
    extra = {"forced": bool(issues), "approved_by_role": ctx.user.role if issues else None, "reason": body.reason, "issues": [i["message"] for i in issues],
             "rules": [{k: i.get(k) for k in ("code", "rule", "limit", "reached")} for i in issues]}
    if current is not None:
        current.employee_id, current.source, current.locked = e.id, "manual", True
        a = current
        for l in ctx.db.scalars(select(m.LockedAssignment).where(m.LockedAssignment.assignment_id == a.id)):
            ctx.db.delete(l)
        action = "assignment.manual_transfer"
    else:
        inp = build_input(ctx.db, p)
        slot = next((s for s in inp.slots if s.id == sh.slot_key), None)
        a = m.Assignment(tenant_id=ctx.tenant_id, period_id=p.id, shift_id=sh.id, employee_id=e.id, source="manual", locked=True)
        ctx.db.add(a)
        ctx.db.flush()
        ctx.db.add(m.Break(tenant_id=ctx.tenant_id, assignment_id=a.id, minutes=sh.break_minutes, paid=False))
        for brand, minutes in (slot.allocations if slot else {}).items():
            ctx.db.add(m.BrandAllocation(tenant_id=ctx.tenant_id, assignment_id=a.id, brand_code=brand, minutes=minutes))
        action = "assignment.manual_assign"
    ctx.db.add(m.LockedAssignment(tenant_id=ctx.tenant_id, assignment_id=a.id, locked_by=ctx.user.id, reason="affectation manuelle"))
    ctx.db.flush()
    guard_monthly_cap(ctx.db, ctx.tenant_id, before_minutes, [e.id], [(sh.day.year, sh.day.month)])  # filet de sécurité : tout ou rien
    ensure_frozen(ctx.db, p)
    regularize.resolve(ctx.db, p.id)  # un transfert peut régulariser une double affectation existante
    reminders = regularize.register_doubles(ctx.db, ctx.tenant_id, p.id, e.id, a.id, ctx.user.id)
    audit(ctx, action, "assignment", a.id, assignment_detail(ctx.db, sh, from_emp, e, **extra))
    return {"assignment_id": str(a.id), "kind": "transfer" if from_emp else "assign", "forced": bool(issues), "conflicts": _conflicts(ctx, p.id),
            "regularizations": reminders}


def _decide(ctx: Ctx, issues: list, people: tuple, force: bool, what: str) -> None:
    """Même décision que pour une affectation manuelle : bloquant -> refus ; alertes sans confirmation -> 409 ; dérogation réservée."""
    refusal = override_refusal(ctx, people)
    if any(i["level"] == "blocking" for i in issues):
        raise HTTPException(409, detail={"code": "blocked", "issues": issues, "can_override": False,
                                         "message": f"{what} impossible : une règle non dérogeable est en cause."})
    if issues and not force:
        raise HTTPException(409, detail={"code": "needs_confirmation", "issues": issues, "can_override": refusal is None, "refusal": refusal,
                                         "message": "Des contraintes ne sont pas respectées. Confirmez pour déroger, ou annulez."})
    if issues and refusal is not None:
        raise HTTPException(403, detail={"code": "forbidden", "issues": issues, "can_override": False, "message": refusal})


def _lock_manual(ctx: Ctx, a: m.Assignment, reason: str) -> None:
    a.source, a.locked = "manual", True
    for lk in ctx.db.scalars(select(m.LockedAssignment).where(m.LockedAssignment.assignment_id == a.id)):
        ctx.db.delete(lk)
    ctx.db.flush()
    ctx.db.add(m.LockedAssignment(tenant_id=ctx.tenant_id, assignment_id=a.id, locked_by=ctx.user.id, reason=reason))


class SwapIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    a: uuid.UUID
    b: uuid.UUID
    expected_a: Optional[uuid.UUID] = None  # titulaires affichés à l'écran (refus si l'un a changé entre-temps)
    expected_b: Optional[uuid.UUID] = None
    force: bool = False
    reason: Optional[str] = Field(None, max_length=300)


@router.post("/periods/{pid}/swap")
def swap(pid: str, body: SwapIn, ctx: Ctx = Depends(require("planning.edit"))):
    """Échange réciproque de deux affectations entre deux collaborateurs, en UNE transaction (tout ou rien). Chacun est contrôlé sur le
    planning qui résulte de l'échange complet, par le même contrôle qu'une affectation manuelle (règles, plafond, dérogations)."""
    p = get_or_404(ctx, m.PlanningPeriod, pid)
    ensure_editable(ctx.db, p.id)
    rows = {a.id: a for a in ctx.db.execute(select(m.Assignment).where(m.Assignment.id.in_([body.a, body.b]), m.Assignment.period_id == p.id)
                                            .with_for_update()).scalars()}
    if body.a == body.b or len(rows) != 2:
        raise HTTPException(404, "Deux affectations distinctes de ce planning sont attendues")
    from ..concurrency import check_holder
    A, B = rows[body.a], rows[body.b]
    if body.expected_a and body.expected_b and A.employee_id == body.expected_b and B.employee_id == body.expected_a:
        return {"already": True, "forced": False, "conflicts": _conflicts(ctx, p.id)}  # échange déjà fait (double clic) : rien n'est refait
    check_holder(A, body.expected_a)
    check_holder(B, body.expected_b)
    return perform_swap(ctx, p, rows[body.a], rows[body.b], body.force, body.reason)


def perform_swap(ctx: Ctx, p: m.PlanningPeriod, A: m.Assignment, B: m.Assignment, force: bool, reason: Optional[str], origin: str = "échange réciproque") -> dict:
    """Échange contrôlé et appliqué (utilisé par le bouton « Échanger » et par l'approbation d'une demande d'échange)."""
    if A.employee_id == B.employee_id:
        raise HTTPException(422, "Les deux affectations appartiennent au même collaborateur : rien à échanger")
    sa, sb = ctx.db.get(m.Shift, A.shift_id), ctx.db.get(m.Shift, B.shift_id)
    e1, e2 = ctx.db.get(m.Employee, A.employee_id), ctx.db.get(m.Employee, B.employee_id)
    pre = Pre(ctx, p)
    issues = _issues(ctx, p, e2, sa, A, pre, moves={sb.slot_key: e1.code}, released=(sb.id,))
    issues += [i for i in _issues(ctx, p, e1, sb, B, pre, moves={sa.slot_key: e2.code}, released=(sa.id,))
               if (i["code"], i["message"]) not in {(x["code"], x["message"]) for x in issues}]
    _decide(ctx, issues, (e1.id, e2.id), force, "Cet échange est")
    months = sorted({(sa.day.year, sa.day.month), (sb.day.year, sb.day.month)})
    before_minutes = month_minutes(ctx.db, [e1.id, e2.id], months)
    A.employee_id, B.employee_id = e2.id, e1.id
    _lock_manual(ctx, A, origin)
    _lock_manual(ctx, B, origin)
    ctx.db.flush()
    guard_monthly_cap(ctx.db, ctx.tenant_id, before_minutes, [e1.id, e2.id], months)  # filet de sécurité : tout ou rien
    ensure_frozen(ctx.db, p)
    regularize.resolve(ctx.db, p.id)
    reminders = regularize.register_doubles(ctx.db, ctx.tenant_id, p.id, e2.id, A.id, ctx.user.id)
    reminders += regularize.register_doubles(ctx.db, ctx.tenant_id, p.id, e1.id, B.id, ctx.user.id)
    extra = {"forced": bool(issues), "approved_by_role": ctx.user.role if issues else None, "reason": reason, "issues": [i["message"] for i in issues]}
    audit(ctx, "assignment.swap", "assignment", A.id, {"a": assignment_detail(ctx.db, sa, e1, e2, **extra), "b": assignment_detail(ctx.db, sb, e2, e1), "origin": origin})
    return {"swapped": [str(A.id), str(B.id)], "forced": bool(issues), "conflicts": _conflicts(ctx, p.id), "regularizations": reminders}


class BulkOp(BaseModel):
    model_config = ConfigDict(extra="forbid")
    assignment_id: uuid.UUID
    to_employee_id: uuid.UUID
    expected_from: Optional[uuid.UUID] = None  # titulaire affiché : refus de TOUTE l'opération si l'un a changé entre-temps


class BulkIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operations: list[BulkOp] = Field(min_length=1, max_length=62)
    force: bool = False
    reason: Optional[str] = Field(None, max_length=300)


@router.post("/periods/{pid}/bulk-transfer")
def bulk_transfer(pid: str, body: BulkIn, ctx: Ctx = Depends(require("planning.edit"))):
    """Modification groupée : plusieurs shifts changent de titulaire en UNE opération (tout ou rien). Chaque transfert est contrôlé par
    le même contrôle qu'une affectation manuelle, sur le planning qui résulte de l'ensemble des transferts ; une seule confirmation."""
    p = get_or_404(ctx, m.PlanningPeriod, pid)
    ensure_editable(ctx.db, p.id)
    ids = [o.assignment_id for o in body.operations]
    if len(set(ids)) != len(ids):
        raise HTTPException(422, "Un même shift apparaît deux fois dans la modification groupée")
    rows = {a.id: a for a in ctx.db.execute(select(m.Assignment).where(m.Assignment.id.in_(ids), m.Assignment.period_id == p.id).with_for_update()).scalars()}
    if len(rows) != len(ids):
        raise HTTPException(404, "Certaines affectations n'appartiennent pas à ce planning")
    emps = {e.id: e for e in ctx.db.scalars(select(m.Employee).where(m.Employee.id.in_({o.to_employee_id for o in body.operations} | {a.employee_id for a in rows.values()})))}
    if any(o.to_employee_id not in emps for o in body.operations):
        raise HTTPException(422, "Collaborateur inconnu")
    from ..concurrency import check_holder
    for o in body.operations:  # un seul shift modifié ailleurs entre-temps : rien n'est fait (tout ou rien) ; déjà transféré : ignoré
        if rows[o.assignment_id].employee_id != o.to_employee_id:
            check_holder(rows[o.assignment_id], o.expected_from)
    shifts = {a.id: ctx.db.get(m.Shift, a.shift_id) for a in rows.values()}
    plan = [(rows[o.assignment_id], shifts[o.assignment_id], emps[o.to_employee_id]) for o in body.operations if rows[o.assignment_id].employee_id != o.to_employee_id]
    if not plan:
        raise HTTPException(422, "Aucun changement : ces shifts appartiennent déjà à ces collaborateurs")
    pre = Pre(ctx, p)
    issues: list = []
    seen: set = set()
    for i, (a, sh, to) in enumerate(plan):
        # référence = planning où les AUTRES transferts sont déjà appliqués : chaque transfert ne signale que ce qu'il provoque
        # (effets combinés compris), daté au bon jour
        moves = {osh.slot_key: oto.code for j, (_oa, osh, oto) in enumerate(plan) if j != i}
        ref = copy.copy(pre)
        ref.base = [dataclasses.replace(x, employee_id=moves[x.slot_id]) if x.slot_id in moves else x for x in pre.base]
        ref.before = set(validate(pre.inp, ref.base))
        ref.minutes_before = {}
        for x in ref.base:
            ref.minutes_before[x.employee_id] = ref.minutes_before.get(x.employee_id, 0) + x.effective_minutes
        released = tuple(osh.id for _oa, osh, _t in plan if _oa.employee_id == to.id)
        for it in _issues(ctx, p, to, sh, a, ref, released=released):
            key = (it["code"], it["message"])
            if key not in seen:
                seen.add(key)
                issues.append({**it, "day": sh.day.isoformat()})
    people = tuple({a.employee_id for a, _s, _t in plan} | {t.id for _a, _s, t in plan})
    _decide(ctx, issues, people, body.force, "Cette modification groupée est")
    months = sorted({(sh.day.year, sh.day.month) for _a, sh, _t in plan})
    before_minutes = month_minutes(ctx.db, list(people), months)
    previous = {a.id: a.employee_id for a, _s, _t in plan}
    for a, _sh, to in plan:
        a.employee_id = to.id
        _lock_manual(ctx, a, "modification groupée")
    ctx.db.flush()
    guard_monthly_cap(ctx.db, ctx.tenant_id, before_minutes, list(people), months)  # filet de sécurité : tout ou rien
    ensure_frozen(ctx.db, p)
    regularize.resolve(ctx.db, p.id)
    reminders = sum((regularize.register_doubles(ctx.db, ctx.tenant_id, p.id, to.id, a.id, ctx.user.id) for a, _s, to in plan), 0)
    for a, sh, to in plan:
        audit(ctx, "assignment.bulk_transfer", "assignment", a.id, assignment_detail(ctx.db, sh, emps.get(previous[a.id]), to, forced=bool(issues), reason=body.reason,
                                                                                    issues=[i["message"] for i in issues if i["day"] == sh.day.isoformat()]))
    return {"changed": len(plan), "forced": bool(issues), "conflicts": _conflicts(ctx, p.id), "regularizations": reminders}


class DuplicateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    days: list[date] = Field(min_length=1, max_length=31)
    force: bool = False
    reason: Optional[str] = Field(None, max_length=300)


@router.post("/assignments/{aid}/duplicate")
def duplicate(aid: str, body: DuplicateIn, ctx: Ctx = Depends(require("planning.edit"))):
    """Duplique un shift affecté (mêmes horaires, site, pause et marques) sur d'autres jours du même planning, pour le même collaborateur.
    Chaque copie passe par le même contrôle qu'une affectation manuelle, en tenant compte des copies précédentes ; tout ou rien."""
    from planning_solver.model import Slot
    from planning_solver.timecalc import shift_hours, split_allocation
    src = get_or_404(ctx, m.Assignment, aid)
    p = ctx.db.get(m.PlanningPeriod, src.period_id)
    ensure_editable(ctx.db, p.id)
    sh = ctx.db.get(m.Shift, src.shift_id)
    e = ctx.db.get(m.Employee, src.employee_id)
    days = sorted(set(body.days))
    bad = [d for d in days if not (p.start_date <= d <= p.end_date) or d == sh.day]
    if bad:
        raise HTTPException(422, "Jours hors du planning ou identiques au shift d'origine : " + ", ".join(f"{d:%d/%m/%Y}" for d in bad))
    weights = {b.brand_code: b.minutes for b in ctx.db.scalars(select(m.BrandAllocation).where(m.BrandAllocation.assignment_id == src.id))}
    if not weights:
        raise HTTPException(422, "Ce shift n'a pas de marque imputée : il ne peut pas être dupliqué")
    pre = copy.copy(Pre(ctx, p))
    issues, plan = [], []
    for d in days:
        h = shift_hours(d, sh.start_time, sh.end_time, sh.break_minutes)
        slot = Slot(f"MANUAL|{uuid.uuid4().hex[:10]}|{d.isoformat()}", d, sh.site_code, sh.start_time, sh.end_time, sh.break_minutes,
                    split_allocation(h.effective_minutes, weights), tag="day", template_id="manual", mandatory=False)
        for i in _issues(ctx, p, e, sh, None, pre, slot=slot):
            issues.append({**i, "day": d.isoformat(), "message": f"{d:%d/%m} — {i['message']}"})
        plan.append((slot, h))
        # la copie suivante est contrôlée sur le planning qui contient déjà celle-ci
        pre.inp = dataclasses.replace(pre.inp, slots=[*pre.inp.slots, slot])
        pre.slots = {**pre.slots, slot.id: slot}
        pre.base = [*pre.base, SAssign(slot.id, e.code, d, slot.start, slot.end, h.presence_minutes, h.break_minutes, h.effective_minutes, dict(slot.allocations), True)]
        pre.before = set(validate(pre.inp, pre.base))
        pre.minutes_before = {**pre.minutes_before, e.code: pre.minutes_before.get(e.code, 0) + h.effective_minutes}
    _decide(ctx, issues, (e.id,), body.force, "Cette duplication est")
    months = sorted({(d.year, d.month) for d in days})
    before_minutes = month_minutes(ctx.db, [e.id], months)
    created = []
    for slot, h in plan:
        nsh = m.Shift(tenant_id=ctx.tenant_id, period_id=p.id, slot_key=slot.id, day=slot.day, site_code=slot.site, start_time=slot.start, end_time=slot.end,
                      break_minutes=slot.break_minutes, presence_minutes=h.presence_minutes, effective_minutes=h.effective_minutes)
        ctx.db.add(nsh)
        ctx.db.flush()
        a = m.Assignment(tenant_id=ctx.tenant_id, period_id=p.id, shift_id=nsh.id, employee_id=e.id, source="manual", locked=True)
        ctx.db.add(a)
        ctx.db.flush()
        ctx.db.add(m.Break(tenant_id=ctx.tenant_id, assignment_id=a.id, minutes=slot.break_minutes, paid=False))
        for brand, minutes in slot.allocations.items():
            ctx.db.add(m.BrandAllocation(tenant_id=ctx.tenant_id, assignment_id=a.id, brand_code=brand, minutes=minutes))
        ctx.db.add(m.LockedAssignment(tenant_id=ctx.tenant_id, assignment_id=a.id, locked_by=ctx.user.id, reason="duplication"))
        created.append((a, nsh))
    ctx.db.flush()
    guard_monthly_cap(ctx.db, ctx.tenant_id, before_minutes, [e.id], months)
    ensure_frozen(ctx.db, p)
    reminders = sum((regularize.register_doubles(ctx.db, ctx.tenant_id, p.id, e.id, a.id, ctx.user.id) for a, _s in created), 0)
    for a, nsh in created:
        audit(ctx, "assignment.duplicate", "assignment", a.id, assignment_detail(ctx.db, nsh, None, e, forced=bool(issues), reason=body.reason,
                                                                               source=str(src.id), issues=[i["message"] for i in issues if i["day"] == nsh.day.isoformat()]))
    return {"created": [{"assignment_id": str(a.id), "shift_id": str(nsh.id), "day": nsh.day.isoformat()} for a, nsh in created],
            "forced": bool(issues), "conflicts": _conflicts(ctx, p.id), "regularizations": reminders}


@router.get("/periods/{pid}/regularizations")
def regularizations(pid: str, ctx: Ctx = Depends(require("planning.read"))):
    """Rappels « À régulariser » encore valides (doubles affectations confirmées provisoirement)."""
    p = get_or_404(ctx, m.PlanningPeriod, pid)
    return regularize.open_items(ctx.db, p.id)


KINDS = {"assignment.manual_assign": "Attribution", "assignment.manual_transfer": "Transfert", "assignment.manual_remove": "Retrait",
         "assignment.reassign": "Réaffectation", "assignment.manual_add": "Ajout d'un shift", "assignment.delete": "Retrait"}


@router.get("/periods/{pid}/history")
def history(pid: str, employee_id: Optional[str] = None, limit: int = 100, ctx: Ctx = Depends(require("planning.read"))):
    """Historique des modifications manuelles : quel collaborateur a été remplacé, par qui, quand."""
    p = get_or_404(ctx, m.PlanningPeriod, pid)
    users = {u.id: u for u in ctx.db.scalars(select(m.User))}
    out = []
    rows = ctx.db.scalars(select(m.AuditLog).where(m.AuditLog.action.in_(list(KINDS))).order_by(m.AuditLog.created_at.desc()).limit(500))
    for r in rows:
        d = r.detail or {}
        if d.get("period_id") != str(p.id) or (employee_id and employee_id not in d.get("employee_ids", [])):
            continue
        u = users.get(r.user_id)
        out.append({"id": str(r.id), "at": r.created_at.isoformat(), "kind": KINDS[r.action], "action": r.action, "by": u.name if u else "—",
                    "day": d.get("day"), "site": d.get("site"), "start": d.get("start"), "end": d.get("end"),
                    "from": (d.get("from") or {}).get("name"), "to": (d.get("to") or {}).get("name"),
                    "forced": bool(d.get("forced")), "reason": d.get("reason"), "issues": d.get("issues", []), "rules": d.get("rules", [])})
        if len(out) >= max(1, min(limit, 300)):
            break
    return out
