"""Vérificateur indépendant des contraintes dures (ne dépend pas de CP-SAT).

`violations()` renvoie des incompatibilités STRUCTURÉES (règle, collaborateur, shifts concernés, limite, valeur atteinte) ;
`validate()` en renvoie le texte « CODE: détail », inchangé, utilisé partout pour comparer deux états d'un planning."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Optional

from .context import PRESENCE_ORDER, presence_ok
from .model import Assignment, Slot, SolverInput, fmt_minutes, month_label
from .sundays import sundays_in
from .timecalc import shift_bounds, shift_hours


@dataclass
class Violation:
    code: str
    text: str  # « CODE: détail » (format historique, stable)
    employee: Optional[str] = None  # identifiant du moteur
    slots: List[str] = field(default_factory=list)  # shifts concernés
    limit: Optional[str] = None  # valeur autorisée, lisible
    reached: Optional[str] = None  # valeur atteinte, lisible
    days: List[date] = field(default_factory=list)  # jours concernés quand aucun shift précis ne l'est (ex. jours hors période)


# --- règles réécrites ici, SANS réutiliser le code du générateur (context.py, model.py) : une erreur commune aux deux ne passerait
#     pas inaperçue. Un test compare ces fonctions à celles du générateur sur de nombreux cas. ---
def _travel(inp: SolverInput, a: str, b: str) -> int:
    """Temps de déplacement déclaré entre deux sites, dans un sens ou dans l'autre (lecture directe des données)."""
    t = getattr(inp, "travel_minutes", {}) or {}
    return max(t.get((a, b), 0), t.get((b, a), 0))


def _interval(sl: Slot):
    """Début et fin réels du shift (fuseau du planning, passage de minuit)."""
    return shift_bounds(sl.day, sl.start, sl.end)


def _break_needed(rules, effective_minutes: int) -> int:
    need = 0
    for over, brk in rules or []:
        if effective_minutes > over and brk > need:
            need = brk
    return need


def _starts_by_site(inp: SolverInput) -> Dict[str, set]:
    out: Dict[str, set] = {}
    for site, starts in (inp.site_starts or {}).items():
        out.setdefault(site, set()).update(starts)
    for sl in inp.slots:
        if sl.site not in (inp.site_starts or {}):
            out.setdefault(sl.site, set()).add(sl.start)
    return out


def _category(sl: Slot, starts: Dict[str, set]):
    if len(starts.get(sl.site, {sl.start})) < 2:
        return None  # boutique à horaire unique : aucune préférence n'a de sens
    minutes = sl.start.hour * 60 + sl.start.minute
    return "matin" if minutes < 9 * 60 else ("middle" if minutes < 12 * 60 else "soir")


def validate(inp: SolverInput, assignments: List[Assignment]) -> List[str]:
    return [v.text for v in violations(inp, assignments)]


def violations(inp: SolverInput, assignments: List[Assignment]) -> List[Violation]:
    slots = {s.id: s for s in inp.slots}
    emps = {e.id: e for e in inp.employees}
    cfg = inp.config
    out: List[Violation] = []

    def add(code: str, text: str, emp: Optional[str] = None, sl=(), limit=None, reached=None, days=()) -> None:
        out.append(Violation(code, text, emp, list(sl), limit, reached, list(days)))

    per_slot: Dict[str, List[str]] = defaultdict(list)
    per_emp: Dict[str, List[Assignment]] = defaultdict(list)
    for a in assignments:
        per_slot[a.slot_id].append(a.employee_id)
        per_emp[a.employee_id].append(a)
    for sid, es in per_slot.items():
        if len(es) > 1:
            add("DOUBLE_ASSIGNMENT", f"DOUBLE_ASSIGNMENT: {sid} pourvu par {es}", sl=[sid], limit="1 titulaire", reached=f"{len(es)} titulaires")

    for sid, eid in inp.locked.items():
        if not any(a.slot_id == sid and a.employee_id == eid for a in assignments):
            add("LOCK_VIOLATED", f"LOCK_VIOLATED: {sid} devait rester à {eid}", emp=eid, sl=[sid])

    for sid in per_slot:
        if sid in inp.frozen_empty:
            add("FROZEN_SLOT", f"FROZEN_SLOT: {sid} hors du périmètre de la réoptimisation", sl=[sid])

    group_count: Dict[str, List[str]] = defaultdict(list)
    for a in assignments:
        s = slots[a.slot_id]
        if s.day_group:
            group_count[s.day_group].append(a.slot_id)
    for g, ids in group_count.items():
        if len(ids) > 1:
            add("DAY_GROUP", f"DAY_GROUP: {g} rempli {len(ids)} fois", sl=ids, limit="1 shift", reached=f"{len(ids)} shifts")

    for eid, lst in per_emp.items():
        e = emps[eid]
        lst.sort(key=lambda a: slots[a.slot_id].bounds[0])
        for a in lst:
            s = slots[a.slot_id]
            one = [a.slot_id]
            if e.excluded:
                add("EXCLUDED_FROM_PERIOD", f"EXCLUDED_FROM_PERIOD: {e.name} sur {a.slot_id} (hors de l'effectif du mois)", eid, one)
            elif e.left_on is not None and s.day >= e.left_on:
                add("EMPLOYEE_REMOVED", f"EMPLOYEE_REMOVED: {e.name} sur {a.slot_id} (retiré·e de l'équipe le {e.left_on:%d/%m/%Y})", eid, one,
                    limit=f"plus de shift à partir du {e.left_on:%d/%m/%Y}", reached=f"shift le {s.day:%d/%m/%Y}")
            elif e.blocked(s.day):
                add("UNAVAILABLE", f"UNAVAILABLE: {e.name} le {s.day} sur {a.slot_id}", eid, one, limit="disponible", reached="indisponible ce jour")
            for wd_, wa, wb in sorted(getattr(e, "unavailable_windows", ()) or ()):
                w0, w1 = shift_bounds(wd_, wa, wb)
                s0, s1 = _interval(s)
                if s0 < w1 and w0 < s1:
                    add("UNAVAILABLE_PARTIAL", f"UNAVAILABLE_PARTIAL: {e.name} le {s.day} sur {a.slot_id} (absent·e de {wa:%H:%M} à {wb:%H:%M})", eid, one,
                        limit=f"absent·e {wa:%H:%M}–{wb:%H:%M}", reached=f"shift {s.start:%H:%M}–{s.end:%H:%M}")
            ww = getattr(e, "work_window", None)
            if ww is not None and not (s.end > s.start and ww[0] <= s.start and s.end <= ww[1]):
                add("WORK_WINDOW", f"WORK_WINDOW: {e.name} sur {a.slot_id} {s.start:%H:%M}-{s.end:%H:%M} hors de ses horaires obligatoires", eid, one,
                    limit=f"{ww[0]:%H:%M}–{ww[1]:%H:%M}", reached=f"{s.start:%H:%M}–{s.end:%H:%M}")
            if s.tag in e.forbidden_tags:
                add("FORBIDDEN_TAG", f"FORBIDDEN_TAG: {e.name} sur {s.id} ({s.tag})", eid, one, reached=s.tag)
            if any(b not in e.brands for b in s.brands):
                miss = [b for b in s.brands if b not in e.brands]
                add("BRAND_NOT_ELIGIBLE", f"BRAND_NOT_ELIGIBLE: {e.name} sur {s.id}", eid, one, limit=", ".join(sorted(e.brands)) or "aucune", reached=", ".join(miss))
            if any(k not in e.skills for k in s.required_skills):
                add("SKILL_MISSING", f"SKILL_MISSING: {e.name} sur {s.id}", eid, one, reached=", ".join(k for k in s.required_skills if k not in e.skills))
            if s.day.weekday() in e.rest_weekdays_hard:
                add("REST_WEEKDAY", f"REST_WEEKDAY: {e.name} sur {s.id} (jour de repos obligatoire)", eid, one)
            if e.allowed_sites is not None and s.site not in e.allowed_sites:
                add("SITE_NOT_ALLOWED", f"SITE_NOT_ALLOWED: {e.name} sur {s.id} ({s.site} hors de ses sites autorisés)", eid, one,
                    limit=", ".join(sorted(e.allowed_sites)) or "aucun", reached=s.site)
            h = shift_hours(s.day, s.start, s.end, s.break_minutes)  # heures recalculées indépendamment du moteur
            if (a.presence_minutes, a.break_minutes, a.effective_minutes) != (h.presence_minutes, h.break_minutes, h.effective_minutes):
                add("HOURS_MISMATCH", f"HOURS_MISMATCH: {a.slot_id} {a.effective_minutes} min enregistrées, {h.effective_minutes} recalculées", eid, one)
            if a.allocations and sum(a.allocations.values()) != a.effective_minutes:
                add("ALLOCATION_MISMATCH", f"ALLOCATION_MISMATCH: {a.slot_id} imputations {sum(a.allocations.values())} min pour {a.effective_minutes} min effectives", eid, one)
            need = _break_needed(cfg.break_rules, h.effective_minutes)
            if s.break_minutes < need:
                add("BREAK_TOO_SHORT", f"BREAK_TOO_SHORT: {a.slot_id} pause de {s.break_minutes} min pour {need} min exigées", eid, one,
                    limit=f"{need} min", reached=f"{s.break_minutes} min")
        for p, q in zip(lst, lst[1:]):
            ep = slots[p.slot_id].bounds[1]
            sq = slots[q.slot_id].bounds[0]
            if sq < ep:
                add("OVERLAP", f"OVERLAP: {e.name} {p.slot_id} / {q.slot_id}", eid, [p.slot_id, q.slot_id])
            elif sq - ep < timedelta(hours=cfg.rest_hours):
                gap = (sq - ep).total_seconds() / 3600
                add("REST", f"REST<{cfg.rest_hours}h: {e.name} {p.slot_id} -> {q.slot_id}", eid, [p.slot_id, q.slot_id],
                    limit=f"{cfg.rest_hours} h", reached=f"{gap:.1f} h".replace(".0 h", " h"))
        # temps de déplacement entre sites : toutes les paires proches (pas seulement les shifts consécutifs)
        longest = max((getattr(inp, "travel_minutes", {}) or {}).values(), default=0)
        for i, p in enumerate(lst):
            ep, sp = slots[p.slot_id].bounds[1], slots[p.slot_id].site
            for q in lst[i + 1:]:
                gap = slots[q.slot_id].bounds[0] - ep
                if gap >= timedelta(minutes=longest):
                    break
                need = _travel(inp, sp, slots[q.slot_id].site)
                if timedelta(0) <= gap < timedelta(minutes=need):
                    add("TRAVEL_TIME", f"TRAVEL_TIME: {e.name} {p.slot_id} -> {q.slot_id} ({sp} -> {slots[q.slot_id].site})", eid,
                        [p.slot_id, q.slot_id], limit=f"{need} min", reached=f"{int(gap.total_seconds() // 60)} min")
        days = sorted({a.day for a in lst})
        # jours travaillés hors période (périodes voisines) : semaines à cheval, jours consécutifs, repos à la frontière
        out_days = {o.day for o in inp.outside_shifts if o.employee_id == eid and not (inp.period_start <= o.day <= inp.period_end)}
        out_days |= {inp.period_start - timedelta(days=k) for k in range(1, e.prior_consecutive_days + 1)}
        all_days = sorted(set(days) | out_days)
        run, prev = 0, None
        for d in all_days:
            run = run + 1 if prev is not None and d - prev == timedelta(days=1) else 1
            if run > cfg.max_consecutive_days and d in days:
                streak = [x.slot_id for x in lst if d - timedelta(days=run - 1) <= x.day <= d]
                add("CONSECUTIVE", f"CONSECUTIVE>{cfg.max_consecutive_days}: {e.name} jusqu'au {d}", eid, streak,
                    limit=f"{cfg.max_consecutive_days} jours", reached=f"{run} jours")
            prev = d
        for o in (o for o in inp.outside_shifts if o.employee_id == eid):
            o0, o1 = shift_bounds(o.day, o.start, o.end)
            for a in lst:
                s0, s1 = slots[a.slot_id].bounds
                if o0 < s1 + timedelta(hours=cfg.rest_hours) and s0 < o1 + timedelta(hours=cfg.rest_hours):
                    add("REST", f"REST<{cfg.rest_hours}h: {e.name} {a.slot_id} avec un shift du {o.day} (période voisine)", eid, [a.slot_id],
                        limit=f"{cfg.rest_hours} h", days=[o.day])
        weeks: Dict[tuple, int] = defaultdict(int)
        for d in set(days) | out_days:
            weeks[d.isocalendar()[:2]] += 1
        wmin: Dict[tuple, int] = defaultdict(int)
        for a in lst:
            wmin[a.day.isocalendar()[:2]] += a.effective_minutes
        wplanned = set(wmin)
        for o in inp.outside_shifts:
            if o.employee_id == eid:
                wmin[o.day.isocalendar()[:2]] += o.minutes  # heures d'une période voisine dans la même semaine

        def in_week(w) -> List[str]:
            return [a.slot_id for a in lst if a.day.isocalendar()[:2] == w]

        week_cap = e.max_days_per_week
        if e.max_days_count is not None and e.max_days_period == "week":
            week_cap = e.max_days_count if week_cap is None else min(week_cap, e.max_days_count)
        if week_cap is not None:
            for w, n in weeks.items():
                if n > week_cap and any(d.isocalendar()[:2] == w for d in days):
                    add("MAX_DAYS_WEEK", f"MAX_DAYS_WEEK: {e.name} {n}>{week_cap} semaine {w}", eid, in_week(w),
                        limit=f"{week_cap} jours dans la semaine", reached=f"{n} jours")
        if e.max_days_count is not None and e.max_days_period == "month" and len(days) > e.max_days_count:
            add("MAX_DAYS_MONTH", f"MAX_DAYS_MONTH: {e.name} {len(days)}>{e.max_days_count} jours sur la période", eid, [a.slot_id for a in lst],
                limit=f"{e.max_days_count} jours", reached=f"{len(days)} jours")
        # par mois civil : jours maximum et plafond d'heures de l'entreprise (tous sites, toutes marques ; périodes voisines du même mois comprises)
        months: Dict[tuple, List[Assignment]] = defaultdict(list)
        for a in lst:
            months[a.day.year, a.day.month].append(a)
        for key, mine in sorted(months.items()):
            o_same = [o for o in inp.outside_shifts if o.employee_id == eid and (o.day.year, o.day.month) == key
                      and not (inp.period_start <= o.day <= inp.period_end)]
            n_days = len({a.day for a in mine} | {o.day for o in o_same})
            if e.max_days_month is not None and n_days > e.max_days_month:
                add("MAX_DAYS_MONTH", f"MAX_DAYS_MONTH: {e.name} {n_days}>{e.max_days_month} jours en {month_label(*key)}", eid, [a.slot_id for a in mine],
                    limit=f"{e.max_days_month} jours", reached=f"{n_days} jours")
            if cfg.monthly_cap_minutes is not None:
                tot = sum(a.effective_minutes for a in mine) + sum(o.minutes for o in o_same)
                # heures fixées avant le calcul (verrous, périodes voisines) : un dépassement existant est toléré, jamais aggravé
                fixed = sum(a.effective_minutes for a in mine if inp.locked.get(a.slot_id) == eid) + sum(o.minutes for o in o_same)
                if tot > max(cfg.monthly_cap_minutes, fixed):
                    add("MONTHLY_CAP", f"MONTHLY_CAP: {e.name} {tot}>{cfg.monthly_cap_minutes} minutes en {month_label(*key)}", eid, [a.slot_id for a in mine],
                        limit=fmt_minutes(cfg.monthly_cap_minutes), reached=fmt_minutes(tot))
        if e.sunday_quota is not None:
            n_sun = sum(1 for d in days if d.weekday() == 6)
            if n_sun > min(e.sunday_quota, len(sundays_in(inp))):
                add("SUNDAY_QUOTA", f"SUNDAY_QUOTA: {e.name} {n_sun}>{e.sunday_quota} dimanche(s)", eid, [a.slot_id for a in lst if a.day.weekday() == 6],
                    limit=f"{e.sunday_quota} dimanche(s)", reached=f"{n_sun} dimanche(s)")
        if e.time_pref and e.time_pref_strict:
            starts = _starts_by_site(inp)
            for a in lst:
                cat = _category(slots[a.slot_id], starts)
                if cat is not None and cat != e.time_pref:
                    add("TIME_PREF_STRICT", f"TIME_PREF_STRICT: {e.name} sur {a.slot_id} ({cat}, préférence {e.time_pref} obligatoire)", eid, [a.slot_id],
                        limit=e.time_pref, reached=cat)
        c = e.contract
        if c and c.weekly_max_minutes is not None:
            for w, mi in wmin.items():
                if w in wplanned and mi > c.weekly_max_minutes:
                    add("CONTRACT_WEEKLY_MAX", f"CONTRACT_WEEKLY_MAX: {e.name} semaine {w}", eid, in_week(w),
                        limit=fmt_minutes(c.weekly_max_minutes), reached=fmt_minutes(mi))
        if e.legal_weekly_max_minutes is not None:
            for w, mi in wmin.items():
                if w in wplanned and mi > e.legal_weekly_max_minutes:
                    add("LEGAL_WEEKLY_MAX", f"LEGAL_WEEKLY_MAX: {e.name} {mi}>{e.legal_weekly_max_minutes} minutes semaine {w}", eid, in_week(w),
                        limit=fmt_minutes(e.legal_weekly_max_minutes), reached=fmt_minutes(mi))
        if c and c.monthly_max_minutes is not None and not c.overtime_allowed:
            tot = sum(a.effective_minutes for a in lst)
            if tot > c.monthly_max_minutes:
                add("CONTRACT_MONTHLY_MAX", f"CONTRACT_MONTHLY_MAX: {e.name}", eid, [a.slot_id for a in lst],
                    limit=fmt_minutes(c.monthly_max_minutes), reached=fmt_minutes(tot))
        if e.weekly_rest_days_hard and e.weekly_rest_days_pref is not None:
            for w, n in weeks.items():
                if n > 7 - e.weekly_rest_days_pref and _full_week(inp, w):
                    add("REST_DAYS_HARD", f"REST_DAYS_HARD: {e.name} semaine {w}", eid, in_week(w),
                        limit=f"{7 - e.weekly_rest_days_pref} jours travaillés", reached=f"{n} jours")

    # minimum de jours par mois civil : contrainte dure (une journée compte une fois ; jours d'une période voisine du même mois compris)
    months = sorted({(d.year, d.month) for d in (inp.period_start + timedelta(days=k) for k in range((inp.period_end - inp.period_start).days + 1))})
    for e in inp.employees:
        if not e.min_days_month or e.excluded or e.left_on is not None:
            continue
        for key in months:
            mine = [a for a in per_emp.get(e.id, ()) if (a.day.year, a.day.month) == key]
            out_d = {o.day for o in inp.outside_shifts if o.employee_id == e.id and (o.day.year, o.day.month) == key
                     and not (inp.period_start <= o.day <= inp.period_end)}
            n_days = len({a.day for a in mine} | out_d)
            if n_days < e.min_days_month:
                add("MIN_DAYS_NOT_MET", f"MIN_DAYS_NOT_MET: {e.name} {n_days}<{e.min_days_month} jours en {month_label(*key)}", e.id,
                    [a.slot_id for a in mine], limit=f"{e.min_days_month} jours", reached=f"{n_days} jours")

    # relations strictes entre collaborateurs (même jour, même site)
    where = {eid: {(slots[a.slot_id].day, slots[a.slot_id].site) for a in lst} for eid, lst in per_emp.items()}

    def at(eid, d, site) -> List[str]:
        return [a.slot_id for a in per_emp.get(eid, ()) if slots[a.slot_id].day == d and slots[a.slot_id].site == site]

    for eid, lst in per_emp.items():
        e = emps[eid]
        tutors = [r for r in e.relations if r.kind == "mentor" and r.strict and r.other in emps]
        t_scope = max((getattr(r, "scope", "site_day") for r in tutors), key=lambda x: PRESENCE_ORDER.get(x, 0)) if tutors else "site_day"
        if tutors and t_scope in ("overlap", "full"):  # chevauchement simple, ou couverture complète de la plage du shift
            for a in lst:
                sa = slots[a.slot_id]
                held = [slots[b.slot_id] for r in tutors for b in per_emp.get(r.other, ()) if slots[b.slot_id].day == sa.day]
                if not presence_ok(sa, held, t_scope):
                    need = "pendant toute la plage" if t_scope == "full" else "en même temps (chevauchement)"
                    add("MENTOR_MISSING", f"MENTOR_MISSING: {e.name} le {sa.day} {sa.start:%H:%M}-{sa.end:%H:%M} à {sa.site} sans tuteur présent {need}",
                        eid, [a.slot_id])
        for d, site in sorted(where[eid]):
            if tutors and t_scope == "site_day" and not any((d, site) in where.get(r.other, ()) for r in tutors):
                add("MENTOR_MISSING", f"MENTOR_MISSING: {e.name} le {d} à {site} sans tuteur présent", eid, at(eid, d, site))
            for r in e.relations:
                if r.kind == "avoid_together" and r.strict and getattr(r, "scope", "site_day") == "site_day" and (d, site) in where.get(r.other, ()) and (
                        eid < r.other or not any(x.kind == r.kind and x.other == eid and x.strict for x in emps[r.other].relations)):
                    add("RELATION_AVOID", f"RELATION_AVOID: {e.name} et {emps[r.other].name} le {d} à {site}", eid, at(eid, d, site) + at(r.other, d, site))
    # « à séparer » de portée élargie (vérification propre, sans le code du générateur) : même jour tous sites, ou horaires qui se chevauchent
    for eid, lst in per_emp.items():
        e = emps[eid]
        for r in e.relations:
            scope = getattr(r, "scope", "site_day")
            if r.kind != "avoid_together" or not r.strict or scope == "site_day" or r.other not in per_emp:
                continue
            if r.other < eid and any(x.kind == r.kind and x.other == eid and x.strict and getattr(x, "scope", "site_day") == scope
                                     for x in emps[r.other].relations):
                continue  # relation réciproque : signalée une seule fois
            for a in lst:
                sa = slots[a.slot_id]
                a0, a1 = _interval(sa)
                for b in per_emp[r.other]:
                    sb = slots[b.slot_id]
                    if scope == "day":
                        hit = sa.day == sb.day
                    else:
                        b0, b1 = _interval(sb)
                        hit = a0 < b1 and b0 < a1
                    if hit:
                        what = f"le {sa.day}" if scope == "day" else f"{sa.day} {sa.start:%H:%M}-{sa.end:%H:%M} / {sb.day} {sb.start:%H:%M}-{sb.end:%H:%M}"
                        add("RELATION_AVOID", f"RELATION_AVOID: {e.name} et {emps[r.other].name} {what} ({'même jour' if scope == 'day' else 'horaires qui se chevauchent'})",
                            eid, [a.slot_id, b.slot_id])

    if inp.allowed_times:
        for a in assignments:
            sl = slots[a.slot_id]
            scopes = [k for k in [sl.site, *sl.brands, *(f"{b}@{sl.site}" for b in sl.brands)] if k in inp.allowed_times]
            if scopes and not any((sl.start, sl.end) in inp.allowed_times[k] for k in scopes):
                add("SCHEDULE_NOT_ALLOWED", f"SCHEDULE_NOT_ALLOWED: {a.slot_id} {sl.start:%H:%M}-{sl.end:%H:%M} hors horaires autorisés ({sl.site})",
                    a.employee_id, [a.slot_id], reached=f"{sl.start:%H:%M}-{sl.end:%H:%M}")
    planned: Dict[str, int] = defaultdict(int)
    for a in assignments:
        for b, mi in a.allocations.items():
            planned[b] += mi
    for b in inp.budgets:
        if b.strict and planned[b.brand] > b.target_minutes:
            add("BUDGET_EXCEEDED", f"BUDGET_EXCEEDED: {b.brand} {planned[b.brand]}>{b.target_minutes}",
                limit=fmt_minutes(b.target_minutes), reached=fmt_minutes(planned[b.brand]))
    return out


def _full_week(inp: SolverInput, week: tuple) -> bool:
    d = inp.period_start
    n = 0
    while d <= inp.period_end:
        if d.isocalendar()[:2] == week:
            n += 1
        d += timedelta(days=1)
    return n == 7
