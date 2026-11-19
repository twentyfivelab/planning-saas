"""Notifications de couverture des marques ajoutées manuellement au planning d'un mois.

Principe : à chaque validation d'une transaction qui a modifié une donnée dont dépend la couverture (affectations, shifts, besoins,
horaires, absences, effectif, règles…), quel qu'en soit l'auteur (écran, import, génération par le moteur), la couverture de chaque suivi
ouvert est recalculée dans la MÊME transaction. Une notification n'est créée que lorsque l'état change :
- vers « complete » : tous les besoins sont attribués, sans conflit ;
- de « complete » vers « incomplete » ou « needs_missing » : la couverture redevient incomplète (ou les besoins ne sont plus définis).
Tant que l'état ne change pas (par exemple 8 puis 9 shifts sur 10), rien n'est envoyé : aucune notification répétée. Un suivi masqué ne
notifie plus. Le destinataire est la personne qui a choisi l'ajout manuel."""
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from . import models as m

log = logging.getLogger(__name__)

# données dont dépend la couverture (besoins, shifts, affectations) ou ses conflits (disponibilités, règles, effectif…)
WATCHED = (m.Assignment, m.Shift, m.BrandAllocation, m.StaffingRequirement, m.ShiftTemplate, m.PeriodBrand, m.PeriodSite, m.PeriodEmployee,
           m.Unavailability, m.PartialAbsence, m.LeaveRequest, m.Availability, m.EmployeeSkill, m.Employee, m.EmploymentContract,
           m.EmployeePreference, m.ConstraintDefinition, m.Brand, m.Site, m.EmployeeMonthParams, m.RelationshipPreference, m.Mission)
FLAG = "coverage_dirty"


def mark(session) -> None:
    """Après chaque écriture : retient qu'une donnée surveillée a changé (évaluation différée à la validation)."""
    if session.info.get(FLAG):
        return
    for obj in (*session.new, *session.dirty, *session.deleted):
        if isinstance(obj, WATCHED):
            session.info[FLAG] = True
            return


def _label(p: m.PlanningPeriod) -> str:
    from .routers.months import MONTHS_FR
    return f"{MONTHS_FR[p.start_date.month - 1].lower()} {p.start_date.year}"


def _h(minutes: int) -> str:
    h, mi = divmod(int(minutes or 0), 60)
    return f"{h} h {mi:02d}" if mi else f"{h} h"


def message(name: str, p: m.PlanningPeriod, cov: dict, state: str) -> tuple:
    label = _label(p)
    if state == "complete":
        return (f"{name} : tous les besoins de {label} sont couverts",
                f"Tous les shifts de {name} sont attribués et sans conflit ({cov['total']} shift(s), {_h(cov['covered_minutes'])}).")
    if state == "needs_missing":
        return (f"{name} : couverture de {label} à revoir", f"Besoins à renseigner : aucun besoin n'est plus défini pour {name} en {label}.")
    detail = ", ".join(x for x in (f"{cov['to_place']} à placer" if cov["to_place"] else "", f"{cov['unassigned']} sans collaborateur" if cov["unassigned"] else "",
                                    f"{cov['conflict']} en conflit" if cov["conflict"] else "") if x)
    return (f"{name} : couverture de {label} de nouveau incomplète",
            f"{cov['remaining']} shift(s) ({_h(cov['remaining_minutes'])}) restent à attribuer" + (f" : {detail}." if detail else "."))


def record(db, it: m.PeriodIntegration, p: m.PlanningPeriod, name: str, cov: dict, notify: bool = True) -> str:
    """Enregistre l'état courant ; notifie seulement s'il a changé (et si la couverture devient complète ou cesse de l'être)."""
    from .coverage import state_of
    state = state_of(cov)
    prev = it.last_state
    it.last_remaining, it.last_remaining_minutes = cov["remaining"], cov["remaining_minutes"]
    if state == prev:
        return state
    it.last_state, it.state_at = state, datetime.now(timezone.utc)
    if notify and prev is not None and (state == "complete" or prev == "complete") and it.chosen_by:
        u = db.get(m.User, it.chosen_by)
        if u is not None and u.is_active:
            title, body = message(name, p, cov, state)
            db.add(m.Notification(tenant_id=it.tenant_id, user_id=u.id, kind="coverage_complete" if state == "complete" else "coverage_incomplete",
                                  title=title, body=body, payload={"period_id": str(p.id), "month": p.start_date.strftime("%Y-%m"), "brand": it.brand_code,
                                                                   "integration_id": str(it.id), "state": state, "remaining": cov["remaining"],
                                                                   "remaining_minutes": cov["remaining_minutes"]}))
    return state


def evaluate(session) -> None:
    """Avant la validation : recalcule les suivis ouverts. Un échec de ce calcul n'empêche jamais la modification de l'utilisateur
    (point de sauvegarde annulé), mais il est journalisé."""
    session.flush()  # écritures encore en attente : prises en compte (et repérées par `mark`)
    if not session.info.pop(FLAG, False):
        return
    rows = list(session.scalars(select(m.PeriodIntegration).where(m.PeriodIntegration.kind == "brand", m.PeriodIntegration.choice == "manual",
                                                                    m.PeriodIntegration.dismissed_at.is_(None))))
    if not rows:
        return
    from .coverage import brand_coverage
    from .services_bridge import build_input
    try:
        with session.begin_nested():
            inputs: dict = {}
            names = {b.code: b.name for b in session.scalars(select(m.Brand))}
            seen = set()
            for it in sorted(rows, key=lambda r: r.created_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True):
                if (it.period_id, it.brand_code) in seen:  # plusieurs choix pour la même marque et le même mois : le plus récent fait foi
                    continue
                seen.add((it.period_id, it.brand_code))
                p = session.get(m.PlanningPeriod, it.period_id)
                if p is None or p.deleted_at is not None or p.archived_at is not None:
                    continue
                inp = inputs.get(p.id) or inputs.setdefault(p.id, build_input(session, p))
                record(session, it, p, names.get(it.brand_code, it.brand_code), brand_coverage(session, p, it.brand_code, inp))
            session.flush()
    except Exception:  # noqa: BLE001 — la modification de l'utilisateur reste enregistrée ; le défaut est visible dans les journaux
        log.exception("Évaluation de la couverture des marques ajoutées impossible")
    session.info.pop(FLAG, None)  # nos propres écritures (notifications, état) ne relancent pas l'évaluation
