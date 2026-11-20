"""Exécution d'une optimisation (worker RQ ou inline)."""
import copy
import logging
import re
import threading
import time
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select

from planning_solver import solve
from planning_solver.context import prepare
from planning_solver.metrics import plan_metrics
from planning_solver.model import OutsideShift
from planning_solver.strategies import BY_KEY as STRATEGIES
from planning_solver.validator import validate
from planning_solver.weights import breakdown

from . import models as m
from . import realtime  # noqa: F401  (le worker annonce aussi la fin des générations)
from .config import settings
from .db import tenant_session
from .frozen import snapshot
from .services_bridge import assignments_for_validation, build_input, current_assignments, params_mode, persist_result
from .versioning import current_map, fingerprint, make_version

log = logging.getLogger(__name__)


def freeze_period(db, period, source: str, capture: dict = None, cap_used=None, used_cfg=None) -> None:
    """Conserve sur le planning les paramètres habituels ACTUELS (ou ceux capturés au lancement du calcul). `used_cfg` : configuration
    réellement utilisée par le calcul (pondérations comprises), pour retrouver les conditions de génération."""
    if capture is None:
        capture = {}
        build_input(db, period, {"params": "current"}, capture=capture)
    cfg = dict(capture["config"])
    if used_cfg is not None:
        cfg["weights"], cfg["hierarchical"] = dict(used_cfg.weights), bool(used_cfg.hierarchical)
    if cap_used is not None or "monthly_cap_minutes" not in cfg:
        cfg["monthly_cap_minutes"] = cap_used
    period.frozen_params = snapshot(capture["employees"], cfg, source)
    period.frozen_at = datetime.now(timezone.utc)
    period.frozen_source = source


def ensure_frozen(db, period, source: str = "manual") -> None:
    """Premier contenu d'un planning (ajout manuel, restauration, simulation appliquée) : ses paramètres sont conservés dès ce moment."""
    if not period.frozen_params:
        freeze_period(db, period, source)


def _version_label(run, when: str) -> str:
    """Nom des versions d'une génération ; une génération lancée pour intégrer un ajout le dit (versions identifiables et comparables)."""
    it = (run.config or {}).get("integration") or {}
    if it.get("name"):
        return f"Avant intégration de {it['name']}" if when == "before" else f"Planning recalculé avec {it['name']}"
    return "Avant génération" if when == "before" else "Planning généré"


def enqueue(tenant_id: str, run_id: str) -> None:
    if settings.opt_execution == "inline":
        run_optimization(tenant_id, run_id)
        return
    from redis import Redis
    from rq import Queue
    Queue("optimization", connection=Redis.from_url(settings.redis_url)).enqueue(
        "app.optimize.run_optimization", tenant_id, run_id, job_timeout=1800)


def _jsonable(o):
    import dataclasses
    from datetime import date, time
    if dataclasses.is_dataclass(o):
        return {k: _jsonable(v) for k, v in dataclasses.asdict(o).items()}
    if isinstance(o, dict):
        return {str(k): _jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple, set)):
        return [_jsonable(v) for v in o]
    if isinstance(o, (date, time, datetime)):
        return o.isoformat()
    return o


def _freeze_outside_scope(inp, prev: dict, locked: dict, config: dict) -> dict:
    """Réoptimisation localisée : seuls les shifts du périmètre sont libres ; tout le reste est figé tel quel (affecté ou vide). Un verrou
    n'est levé que si son titulaire ne peut plus assurer le shift. Renvoie les verrous conservés par le solveur."""
    from datetime import date, timedelta
    free = set(config.get("free_slots", []))
    radius = int(config.get("radius_days") or 0)
    if radius:
        days = {date.fromisoformat(d) for d in config.get("free_days", [])}
        near = {d + timedelta(days=k) for d in days for k in range(-radius, radius + 1)}
        free |= {s.id for s in inp.slots if s.day in near and s.id not in locked}
    prep = prepare(inp)
    slots = {s.id: s for s in inp.slots}
    fixed, removed = {}, []
    for sid, eid in prev.items():
        if sid not in slots:
            continue
        if sid in free and sid not in locked:
            continue
        if (eid, sid) in prep.eligible:
            fixed[sid] = eid
        elif sid in locked and sid in free:
            continue  # le titulaire ne peut plus assurer ce shift verrouillé : le manager l'a inclus dans le périmètre
        elif sid in locked:
            removed.append(sid)  # dérogation enregistrée, hors périmètre : conservée et comptée comme shift déjà planifié
        else:
            free.add(sid)  # le titulaire ne peut plus l'assurer : à réaffecter, le figer rendrait le problème impossible
    for sid in removed:
        s = slots[sid]
        inp.outside_shifts.append(OutsideShift(prev[sid], s.day, s.start, s.end, s.effective_minutes))
    if removed:
        gone = set(removed)
        inp.slots = [s for s in inp.slots if s.id not in gone]
    inp.frozen_empty = {s.id for s in inp.slots if s.id not in free and s.id not in fixed}
    return fixed


def _keep_locks_of_removed(inp) -> None:
    """Affectation verrouillée d'un collaborateur supprimé, à partir de sa date de retrait : conservée telle quelle (historique), sortie du
    calcul et comptée comme shift déjà planifié ; aucun nouveau shift ne lui est attribué."""
    emps = {e.id: e for e in inp.employees}
    slots = {s.id: s for s in inp.slots}
    gone = [sid for sid, eid in inp.locked.items() if eid in emps and emps[eid].left_on is not None and sid in slots and slots[sid].day >= emps[eid].left_on]
    for sid in gone:
        s = slots[sid]
        inp.outside_shifts.append(OutsideShift(inp.locked.pop(sid), s.day, s.start, s.end, s.effective_minutes))
    if gone:
        drop = set(gone)
        inp.slots = [s for s in inp.slots if s.id not in drop]
        inp.previous = {k: v for k, v in inp.previous.items() if k not in drop}


_CAP = re.compile(r"^MONTHLY_CAP: (.+) (\d+)>(\d+) minutes en (.+)$")


def new_violations(found, before) -> list:
    """Violations absentes de l'état précédent. Un dépassement du plafond mensuel qui existait déjà et n'augmente pas (heures inchangées ou
    réduites) n'est pas nouveau : un planning établi avant le plafond peut être corrigé, jamais aggravé."""
    prev = {}
    for v in before:
        mm = _CAP.match(v)
        if mm:
            prev[mm.group(1), mm.group(4)] = int(mm.group(2))
    out = []
    for v in found:
        if v in before:
            continue
        mm = _CAP.match(v)
        if mm and (mm.group(1), mm.group(4)) in prev and int(mm.group(2)) <= prev[mm.group(1), mm.group(4)]:
            continue
        out.append(v)
    return out


def _volume(inp, slot_ids) -> dict:
    """Volume attribué : shifts et heures, obligatoires et optionnels (besoins saisis du mois)."""
    slots = {s.id: s for s in inp.slots}
    out = {"mandatory": 0, "optional": 0, "minutes": 0, "optional_minutes": 0, "other": 0}
    for sid in slot_ids:
        s = slots.get(sid)
        if s is None:
            out["other"] += 1  # shift ajouté à la main ou besoin retiré depuis
            continue
        out["minutes"] += s.effective_minutes
        if s.mandatory:
            out["mandatory"] += 1
        else:
            out["optional"] += 1
            out["optional_minutes"] += s.effective_minutes
    return out


# limites dures représentées seulement dans la capacité seul, ou pas du tout, dans le calcul de la cible (jamais dans le planning : le
# moteur et le vérificateur indépendant les appliquent toujours)
FLOW_NOT_REPRESENTED = ("repos minimal entre deux shifts", "jours consécutifs maximum", "minimum de jours")


def fairness_report(inp, res) -> dict:
    """Bilan d'équité d'un calcul. Pour chaque collaborateur : heures RÉELLEMENT attribuées (toutes, y compris les besoins optionnels sans
    budget, comptées à part), cible, nature de la cible (estimée ou calculée sur le volume décidé), atteinte (démontrée par le planning,
    ou optimum d'équité prouvé, ou non démontrée) et limites que le calcul de la cible ne représente qu'en partie."""
    from planning_solver.context import prepare, realized_targets
    fp = prepare(inp)
    hier = bool(inp.config.hierarchical)
    tg, rf = realized_targets(fp, [x.slot_id for x in res.assignments]) if hier else (fp.targets, fp.fair_ref)
    lv = {x.get("level"): x for x in (res.to_dict().get("levels") or [])}
    eq_proved = bool((lv.get("equite") or {}).get("proved_optimal")) if hier else bool((lv.get("pondere") or {}).get("proved_optimal"))
    mins, extra = {}, {}
    for x in res.assignments:
        s_ = fp.slots.get(x.slot_id)
        mins[x.employee_id] = mins.get(x.employee_id, 0) + x.effective_minutes
        if s_ is not None and not s_.mandatory and not any(b in fp.budgeted_brands for b in s_.brands):
            extra[x.employee_id] = extra.get(x.employee_id, 0) + x.effective_minutes
    out = {}
    for e in inp.employees:
        if e.excluded or e.left_on is not None:
            continue
        opts = fp.by_emp.get(e.id, ())
        t, mi = tg.get(e.id, 0), mins.get(e.id, 0)
        half = max((s_.effective_minutes for s_ in opts), default=0) // 2
        if not opts:
            status = "aucun shift possible"
        elif not hier:
            status = "estimée"
        elif abs(mi - t) <= half:
            status = "atteinte"  # démontrée : le planning lui-même l'atteint (à moins d'un demi-shift près)
        elif eq_proved:
            status = "optimum prouvé"  # aucune répartition respectant toutes les règles ne réduit davantage les écarts
        else:
            status = "non démontrée"
        partial = []
        if e.max_days_month or (e.max_days_count and e.max_days_period == "month") or (e.contract and e.contract.monthly_max_minutes):
            partial.append("limites mensuelles (dans sa capacité seule, pas dans le partage entre collègues)")
        if e.sunday_quota is not None:
            partial.append("quota de dimanches")
        if any(getattr(r, "strict", False) for r in (e.relations or [])):
            partial.append("relations strictes")
        out[e.id] = {"name": e.name, "minutes": mi, "unbudgeted_minutes": extra.get(e.id, 0), "target": t, "ref": rf.get(e.id, 0),
                     "cap": fp.fair_cap.get(e.id, 0), "eligible": len(opts), "explicit": e.id in fp.fair_explicit,
                     "reinforce_only": bool(opts) and all(all(e.brands.get(b) == "reinforce" for b in s_.brands) for s_ in opts),
                     "target_status": status, "partially_represented": partial}
    decided = sum(s_.effective_minutes for sid in {x.slot_id for x in res.assignments} if (s_ := fp.slots.get(sid)) is not None
                  and (s_.mandatory or any(b in fp.budgeted_brands for b in s_.brands)))
    meta = {"mode": "hierarchique" if hier else "un_seul_niveau",
            "target_basis": "volume décidé par le calcul (obligatoires et budgets)" if hier else "estimation avant calcul (obligatoires et budgets du mois)",
            "decided_minutes": decided if hier else fp.fair_supply, "assigned_minutes": sum(mins.values()), "unbudgeted_minutes": sum(extra.values()),
            "equity_level_proved": eq_proved, "flow_represents": ["shifts autorisés (renfort compris)", "un shift par jour",
                                                                  "jours et heures maximum par semaine", "partage des shifts entre collègues"],
            "flow_not_represented": list(FLOW_NOT_REPRESENTED)}
    return {"fairness": out, "fairness_meta": meta}


def _volume_report(inp, before_ids, after_ids) -> dict:
    """Évolution du volume, présentée à part de l'équité : toute baisse des shifts optionnels est visible et expliquée."""
    b, a = _volume(inp, before_ids), _volume(inp, after_ids)
    budgeted = {x.brand for x in inp.budgets}
    no_budget = sorted({br for s in inp.slots if not s.mandatory for br in s.brands} - budgeted)
    d, dm = a["optional"] - b["optional"], a["optional_minutes"] - b["optional_minutes"]
    note = None
    if before_ids and d > 0 and no_budget:
        note = (f"{d} shift(s) optionnel(s) de plus que dans le planning remplacé (+{dm // 60} h) : besoins optionnels sans budget de "
                f"{', '.join(no_budget)} retenus pour rapprocher les collaborateurs les moins chargés de la cible commune d'heures. "
                "Ce sont des besoins réels du mois ; vous pouvez les retirer ou saisir un budget pour fixer ce volume.")
    elif before_ids and d < 0:
        h = -dm // 60
        note = (f"{-d} shift(s) optionnel(s) de moins que dans le planning remplacé ({h} h). "
                + (f"Les besoins optionnels de {', '.join(no_budget)} n'ont pas de budget ce mois-ci : aucun volume n'est visé pour eux, "
                   "le moteur ne retient que ce qu'il faut pour équilibrer les heures. " if no_budget else
                   "Les budgets du mois sont atteints avec moins de shifts optionnels. ")
                + "Vous pouvez compléter les besoins optionnels non attribués à la main depuis le planning.")
    return {"before": b, "after": a, "delta_optional": d, "delta_optional_minutes": dm, "optional_without_budget": no_budget, "note": note}


def plan_state(db, period_id) -> dict:
    """État exact du planning : pour chaque shift, titulaire, horaires, pause et verrou (relu en base, jamais depuis le cache de la session)."""
    rows = db.execute(select(m.Shift.slot_key, m.Shift.start_time, m.Shift.end_time, m.Shift.break_minutes, m.Assignment.employee_id, m.Assignment.locked)
                      .outerjoin(m.Assignment, m.Assignment.shift_id == m.Shift.id).where(m.Shift.period_id == period_id)
                      .execution_options(populate_existing=True)).all()
    return {k: (str(e) if e else None, st.isoformat(), en.isoformat(), b, bool(lk)) for k, st, en, b, e, lk in rows}


def diff_states(a: dict, b: dict) -> list:
    """Shifts dont l'état diffère entre deux relevés (ajoutés, retirés ou modifiés), triés."""
    return sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))


def _save_kept(res, before_state: dict, cancelled: bool, deleted: bool = False) -> dict:
    """Résultat d'enregistrement quand aucun nouveau planning n'est écrit : l'ancien est conservé, avec la raison exploitable."""
    first = next((i.message for i in res.diagnostics if i.severity == "blocking"), None) or (res.diagnostics[0].message if res.diagnostics else None)
    if deleted:
        code, reason = "period_deleted", "Le planning a été supprimé pendant le calcul : rien n'a été enregistré."
    elif cancelled:
        code, reason = "cancelled", "Calcul annulé : le planning existant n'a pas été modifié."
    elif res.status == "infaisable":
        code, reason = "infeasible", "Aucun planning ne respecte toutes les contraintes obligatoires" + (f" : {first}" if first else ".")
    elif res.status == "interrompu" and not res.assignments:
        code, reason = "no_solution_in_time", "Aucune solution trouvée dans la durée maximale : relancez avec une durée plus longue."
    else:
        code, reason = "not_saved", "Aucun planning enregistré."
    return {"outcome": "kept_previous", "reason_code": code, "reason": reason, "before": before_state, "after": before_state}


class PlanRejected(Exception):
    """Le planning enregistré enfreint une contrainte stricte : la transaction d'enregistrement est annulée."""

    def __init__(self, violations):
        super().__init__("planning rejeté")
        self.violations = violations


def verify_on_fresh_data(db, period, config: dict, plan: list, kept_locks: dict) -> list:
    """Vérificateur indépendant sur les données RELUES après le calcul : une absence saisie pendant le calcul, un besoin retiré ou un verrou posé entre-temps est détecté."""
    fresh = build_input(db, period, config)
    known = {s.id for s in fresh.slots}
    gone = [f"BESOIN_RETIRE: {a.slot_id} n'existe plus" for a in plan if a.slot_id not in known]
    fresh.locked = dict(kept_locks)
    return gone + validate(fresh, [a for a in plan if a.slot_id in known])


def verify_saved_plan(db, period, config: dict, before: set) -> dict:
    """Vérificateur indépendant sur le planning réellement enregistré. Seules les violations nouvelles le font rejeter (une dérogation déjà accordée reste signalée)."""
    fresh = build_input(db, period, config)
    saved = assignments_for_validation(db, fresh, period)
    found = set(validate(fresh, saved))
    n_rows = db.scalar(select(func.count()).select_from(m.Assignment).where(m.Assignment.period_id == period.id)) or 0
    fresh_new = new_violations(found, before)
    return {"checked": len(saved), "unchecked": n_rows - len(saved), "violations": sorted(fresh_new), "already_known": len(found) - len(fresh_new)}


def run_optimization(tenant_id: str, run_id: str) -> None:
    cancel = threading.Event()
    stop = threading.Event()
    state = {"progress": {"phase": "preparing"}, "sent": None}

    def on_progress(p: dict) -> None:
        state["progress"] = p

    def push(db) -> None:
        cur = state["progress"]
        if cur is not state["sent"]:
            r = db.get(m.OptimizationRun, uuid.UUID(run_id))
            if r is not None:
                r.progress = dict(cur)
            state["sent"] = cur

    def watch():  # relaie cancel_requested (base) vers le solveur et publie l'état du calcul (au plus une fois par seconde)
        while not stop.wait(1.0):
            with tenant_session(tenant_id) as db:
                r = db.get(m.OptimizationRun, uuid.UUID(run_id))
                if r is not None and r.cancel_requested:
                    cancel.set()
                    return
                push(db)

    t_start = time.time()
    try:
        with tenant_session(tenant_id) as db:
            run = db.get(m.OptimizationRun, uuid.UUID(run_id))
            if run is None or run.cancel_requested:
                if run is not None:
                    run.status = "annule"
                return
            run.status, run.started_at = "en_cours", datetime.now(timezone.utc)
            run.progress = {"phase": "preparing"}
            period = db.get(m.PlanningPeriod, run.period_id)
            # le plafond mensuel ACTUEL de l'entreprise s'applique à tout calcul ; les autres paramètres sont ceux du planning,
            # sauf choix explicite des paramètres actuels (config["params"] == "current")
            config = {**(run.config or {}), "cap": "current", "generation": True}
            mode_used = params_mode(period, config)
            captured: dict = {}
            inp = build_input(db, period, config, capture=captured)
            prev, locked = current_assignments(db, period)
            simulation = run.simulation
            keep_current = run.kind in ("partial", "local") or STRATEGIES.get(config.get("strategy"), {}).get("keep_current", False)
            inp.previous = prev if keep_current else {}
            inp.locked = _freeze_outside_scope(inp, prev, locked, config) if run.kind == "local" else locked
            _keep_locks_of_removed(inp)
            base_fp = fingerprint(current_map(db, period.id))
            start_state = plan_state(db, period.id)  # état exact au démarrage : toute modification pendant le calcul sera détectée
            before_plan = build_input(db, period, config)
            before_violations = set(validate(before_plan, assignments_for_validation(db, before_plan, period)))
            used_locks = dict(inp.locked)
            # état du planning AVANT le calcul (diagnostic d'enregistrement : ce qui a été remplacé ou conservé)
            before_state = {"assignments": len(prev), "locked": len(locked), "version": db.scalar(
                select(func.max(m.ScheduleVersion.number)).where(m.ScheduleVersion.period_id == period.id))}
        threading.Thread(target=watch, daemon=True).start()
        t_solve = time.time()
        res = solve(inp, cancel, on_progress)
        t_solved = time.time()
        stop.set()
        with tenant_session(tenant_id) as db:
            run = db.get(m.OptimizationRun, uuid.UUID(run_id))
            # planning verrouillé pendant l'enregistrement (même verrou que sa suppression) : supprimé pendant le calcul -> rien n'est écrit
            period = db.execute(select(m.PlanningPeriod).where(m.PlanningPeriod.id == run.period_id).with_for_update()).scalar_one()
            gone = period.deleted_at is not None
            run.progress = {**(state["progress"] or {}), "phase": "saving", "elapsed_s": res.duration_s, "time_limit_s": inp.config.time_limit_s}
            report = _jsonable({k: v for k, v in res.to_dict().items() if k != "assignments"})
            report["weights_used"] = res.weights
            try:  # bilan d'équité : mêmes cibles que le moteur, toutes les heures réellement attribuées, nature et atteinte de chaque cible
                report.update(fairness_report(inp, res))
            except Exception:  # noqa: BLE001 — diagnostic d'affichage seulement : jamais bloquant pour l'enregistrement
                log.exception("équité : détail non calculé")
            report["criteria_scores"] = breakdown(res.objective)  # coût par critère : quels critères ont influencé le choix
            # vérification indépendante, sans exception dès qu'un planning existe (optimal, valide, partiel, interrompu, simulation, réoptimisation)
            verification = {"executed": bool(res.assignments), "status": res.status, "kind": run.kind, "simulation": simulation,
                            "solver_result": {"checked": len(res.assignments), "violations": list(res.hard_violations)}}
            if res.assignments:
                fresh_violations = verify_on_fresh_data(db, period, config, res.assignments, used_locks)
                verification["fresh_data"] = {"checked": len(res.assignments), "violations": fresh_violations}
                new = [v for v in new_violations(fresh_violations, before_violations) if v not in res.hard_violations]
                if new:
                    res.hard_violations = list(res.hard_violations) + new
                    report["hard_violations"] = res.hard_violations
            else:
                verification["reason"] = "Aucun planning produit : rien à vérifier, rien n'est enregistré."
            report["verification"] = verification
            report["save"] = _save_kept(res, before_state, cancel.is_set(), gone)  # remplacé ci-dessous si le planning est enregistré
            report["timing"] = {"preparation_s": round(t_solve - t_start, 3), **(res.timing or {}), "solver_call_s": round(t_solved - t_solve, 3)}
            report["params_used"] = {"mode": mode_used, "frozen_at": period.frozen_at.isoformat() if mode_used == "frozen" and period.frozen_at else None,
                                     "monthly_cap_minutes": inp.config.monthly_cap_minutes}
            if simulation:  # une simulation n'écrit JAMAIS dans le planning : elle garde sa proposition jusqu'à une application explicite
                report["save"] = {"outcome": "simulation", "reason_code": "simulation", "reason": "Proposition calculée : le planning n'est pas modifié tant qu'elle n'est pas appliquée.",
                                  "before": before_state, "after": before_state}
                report["timing"]["total_s"] = round(time.time() - t_start, 3)
                report["base_fingerprint"] = base_fp
                known = {s.id for s in inp.slots}
                reference = {k: v for k, v in prev.items() if k in known} if run.kind == "local" else prev
                report["metrics"] = _jsonable(plan_metrics(inp, res.assignments, reference=reference)) if res.assignments else _jsonable(res.metrics)
                if not res.hard_violations:
                    report["proposal"] = [{"slot_id": a.slot_id, "employee_id": a.employee_id, "day": a.day.isoformat(), "start": a.start.isoformat()[:5], "end": a.end.isoformat()[:5],
                                           "site": next((s.site for s in inp.slots if s.id == a.slot_id), None)} for a in res.assignments]
                db.add(m.OptimizationResult(tenant_id=run.tenant_id, run_id=run.id, status=res.status, mode=res.mode, duration_s=res.duration_s, report=report))
                run.status = "annule" if cancel.is_set() else "termine"
                run.finished_at = datetime.now(timezone.utc)
                db.add(m.AuditLog(tenant_id=run.tenant_id, action="simulation.finished", entity="run", entity_id=str(run.id),
                                  detail={"status": res.status, "strategy": config.get("strategy"), "kind": run.kind}))
                return
            # ligne enregistrée tôt (le statut « exploratoire » des versions s'en sert) ; le rapport définitif est écrit en sortie
            row = m.OptimizationResult(tenant_id=run.tenant_id, run_id=run.id, status=res.status, mode=res.mode, duration_s=res.duration_s, report=copy.deepcopy(report))
            db.add(row)
            # garde-fou : un planning qui enfreint une contrainte dure n'est JAMAIS enregistré (vérification indépendante)
            if res.hard_violations:
                report["blocked_by_verification"] = res.hard_violations
                report["save"] = {**report["save"], "outcome": "kept_previous", "reason_code": "verification_failed",
                                  "reason": f"La solution trouvée enfreint {len(res.hard_violations)} contrainte(s) obligatoire(s) selon la vérification indépendante : elle n'a pas été enregistrée."}
                report["timing"]["total_s"] = round(time.time() - t_start, 3)
                row.report = report
                db.add(m.Conflict(tenant_id=run.tenant_id, run_id=run.id, code="PLAN_REJECTED", severity="blocking",
                                  message="Planning refusé par la vérification automatique : " + "; ".join(res.hard_violations[:5]),
                                  slots=[]))
                run.status, run.finished_at = "erreur", datetime.now(timezone.utc)
                return
            # modifications faites PENDANT le calcul (réaffectation, horaires, ajout, retrait, verrou) : jamais écrasées. Les shifts puis les
            # affectations du mois sont verrouillés (même ordre que les modifications, qui sont attendues si elles sont en cours), puis l'état
            # est comparé à celui du démarrage ; s'il a changé, le résultat n'est pas enregistré et la raison est donnée (relancer le calcul).
            changed = []
            if not cancel.is_set() and not gone:
                db.execute(select(m.Shift.id).where(m.Shift.period_id == period.id).order_by(m.Shift.id).with_for_update())
                db.execute(select(m.Assignment.id).where(m.Assignment.period_id == period.id).order_by(m.Assignment.id).with_for_update())
                changed = diff_states(start_state, plan_state(db, period.id))
            if changed:
                report["save"] = {"outcome": "kept_previous", "reason_code": "modified_during_run", "before": before_state, "after": before_state,
                                  "changes": len(changed), "changed_examples": changed[:5],
                                  "reason": f"Le planning a été modifié pendant le calcul ({len(changed)} shift(s) : réaffectation, horaires, ajout, retrait "
                                            "ou verrou) : le résultat n'a pas été enregistré pour ne pas écraser ces modifications. Relancez le calcul pour en tenir compte."}
            # annulation demandée (avant ou pendant la recherche) : la solution partielle n'est JAMAIS enregistrée, le planning existant reste
            if not changed and not cancel.is_set() and not gone and (res.status in ("optimal", "faisable", "partiellement_couvert") or (
                    res.status == "interrompu" and res.assignments)):
                try:
                    with db.begin_nested():  # enregistrement et vérification du planning enregistré : tout ou rien
                        if prev:  # le planning remplacé reste récupérable
                            make_version(db, run.tenant_id, period.id, _version_label(run, "before"), "safety", run.requested_by)
                        persist_result(db, run.tenant_id, period, inp, res, run.id)
                        db.flush()
                        from . import regularize
                        regularize.resolve(db, period.id)
                        saved = verify_saved_plan(db, period, config, before_violations)
                        verification["after_save"] = saved
                        if saved["violations"]:
                            raise PlanRejected(saved["violations"])
                        v_after = make_version(db, run.tenant_id, period.id, _version_label(run, "after"), "generated", run.requested_by, run_id=run.id)
                        n_after = db.scalar(select(func.count()).select_from(m.Assignment).where(m.Assignment.period_id == period.id)) or 0
                        n_locked = db.scalar(select(func.count()).select_from(m.Assignment).where(m.Assignment.period_id == period.id, m.Assignment.locked.is_(True))) or 0
                        report["save"] = {"outcome": "replaced", "reason_code": "saved", "reason": "Nouveau planning vérifié puis enregistré.",
                                          "before": before_state, "after": {"assignments": n_after, "locked": n_locked, "version": v_after.number},
                                          "volume": _volume_report(inp, list(prev), [x.slot_id for x in res.assignments])}
                        # paramètres conservés par ce planning : ceux du calcul (actuels si choisis ou si le planning n'en avait pas)
                        if mode_used == "current":
                            freeze_period(db, period, "generation", captured, inp.config.monthly_cap_minutes, used_cfg=inp.config)
                        else:
                            fp = dict(period.frozen_params)
                            fp["config"] = {**fp.get("config", {}), "monthly_cap_minutes": inp.config.monthly_cap_minutes,
                                            "weights": dict(inp.config.weights), "hierarchical": bool(inp.config.hierarchical)}
                            period.frozen_params = fp
                        period.frozen_params = {**period.frozen_params, "generation_run_id": str(run.id)}  # calcul à l'origine du planning
                except PlanRejected as exc:
                    report["blocked_by_verification"] = exc.violations
                    report["save"] = {"outcome": "kept_previous", "reason_code": "rejected_after_save", "before": before_state, "after": before_state,
                                      "reason": f"Le planning enregistré enfreignait {len(exc.violations)} contrainte(s) obligatoire(s) à la relecture : l'enregistrement a été annulé."}
                    report["timing"]["total_s"] = round(time.time() - t_start, 3)
                    row.report = report
                    db.add(m.Conflict(tenant_id=run.tenant_id, run_id=run.id, code="PLAN_REJECTED", severity="blocking",
                                      message="Planning refusé par la vérification du planning enregistré : " + "; ".join(exc.violations[:5]), slots=[]))
                    run.status, run.finished_at = "erreur", datetime.now(timezone.utc)
                    return
            report["timing"]["total_s"] = round(time.time() - t_start, 3)
            report["timing"]["saving_s"] = round(time.time() - t_solved, 3)
            row.report = report
            for i in res.diagnostics + res.missing_data:
                if i.severity != "info":
                    db.add(m.Conflict(tenant_id=run.tenant_id, run_id=run.id, code=i.code, severity=i.severity,
                                      message=i.message, slots=i.slots))
            run.status = "annule" if cancel.is_set() else "termine"
            run.finished_at = datetime.now(timezone.utc)
            saved = res.status in ("optimal", "faisable", "partiellement_couvert") or (res.status == "interrompu" and bool(res.assignments))
            db.add(m.AuditLog(tenant_id=run.tenant_id, user_id=run.requested_by, action="optimization.finished", entity="run",
                              entity_id=str(run.id), detail={"status": res.status, "mode": res.mode, "kind": run.kind, "saved": saved,
                                                             "period_id": str(period.id), "period": period.name,
                                                             "assignments": len(res.assignments), "uncovered": len(res.uncovered_slots)}))
    except Exception as exc:  # noqa: BLE001 — statut d'erreur sans détail sensible
        stop.set()
        with tenant_session(tenant_id) as db:
            run = db.get(m.OptimizationRun, uuid.UUID(run_id))
            if run is not None:
                run.status, run.finished_at = "erreur", datetime.now(timezone.utc)
                db.add(m.OptimizationResult(tenant_id=run.tenant_id, run_id=run.id, status="interrompu",
                                            mode="n/a", duration_s=0.0, report={"error": type(exc).__name__}))
        raise
