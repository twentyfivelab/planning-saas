"""Historique des modifications : lecture du journal d'audit existant (aucune copie), présentée en langage simple.

Chaque événement distingue la DATE DE MODIFICATION (heure exacte, fuseau de l'entreprise) de la DATE DU SHIFT concerné. Seules les
opérations réellement enregistrées apparaissent : le journal est écrit dans la même transaction que la modification, une opération
refusée ou annulée n'y laisse aucune trace. Les informations absentes des anciens événements (marque, auteur…) sont affichées comme
« non enregistré », jamais déduites. Les noms sont ceux figés au moment de la modification : un collaborateur retiré reste lisible."""
import uuid
from collections import OrderedDict
from datetime import date, datetime, time, timedelta, timezone
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from .. import models as m
from ..deps import Ctx, CtxDep
from ..rbac import has_permission

router = APIRouter(tags=["historique des modifications"])

MONTHS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre")
DAYS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
NOT_RECORDED = "non enregistré"

# action du journal -> type affiché (filtre « type d'action »)
KIND_OF = {
    "assignment.manual_add": "add", "assignment.duplicate": "add",
    "assignment.manual_remove": "remove", "assignment.delete": "remove", "assignment.mission_release": "remove",
    "assignment.manual_transfer": "replace", "assignment.reassign": "replace", "assignment.manual_assign": "replace",
    "assignment.swap": "swap", "assignment.bulk_transfer": "bulk",
    "shift.edit": "hours",
    "assignment.lock": "lock", "assignment.unlock": "lock",
    "optimization.finished": "generation", "simulation.applied": "generation",
    "version.restore": "restore", "version.publish": "publish", "version.create": "version", "version.validate": "version",
    "period.deleted": "deletion",
}
KIND_LABEL = {"add": "Ajout", "remove": "Suppression", "replace": "Remplacement", "swap": "Échange", "bulk": "Modification groupée",
              "hours": "Changement d'horaires", "lock": "Verrouillage", "generation": "Génération", "restore": "Restauration",
              "publish": "Publication", "version": "Version", "deletion": "Suppression d'un planning"}
GROUPED = {"assignment.bulk_transfer", "assignment.duplicate", "assignment.mission_release"}  # une opération = plusieurs lignes du journal


def _tz(ctx: Ctx) -> ZoneInfo:
    t = ctx.db.get(m.Tenant, ctx.tenant_id)
    try:
        return ZoneInfo(t.timezone if t and t.timezone else "Europe/Zurich")
    except Exception:  # noqa: BLE001 — fuseau inconnu : celui par défaut de l'application
        return ZoneInfo("Europe/Zurich")


def _when(dt: datetime, tz: ZoneInfo, now: datetime) -> str:
    x = dt.astimezone(tz)
    year = "" if x.year == now.astimezone(tz).year else f" {x.year}"
    return f"{x.day} {MONTHS[x.month - 1]}{year} à {x:%H:%M}"


def _day(iso: Optional[str]) -> Optional[str]:
    if not iso:
        return None
    d = date.fromisoformat(iso[:10])
    return f"{DAYS[d.weekday()]} {d.day} {MONTHS[d.month - 1]} {d.year}"


def _hm(v: Optional[str]) -> str:
    return v[:5] if v else "—"


def _name(x) -> Optional[str]:
    return x.get("name") if isinstance(x, dict) else None


def _where(d: dict) -> str:
    """« sur Valmont » (marque) ou, à défaut, « à GVA3 » (site) ; rien si l'information n'a pas été enregistrée."""
    if d.get("brands"):
        return " sur " + " / ".join(d["brands"])
    if d.get("site_name") or d.get("site"):
        return " à " + (d.get("site_name") or d["site"])
    return ""


def _render(r: m.AuditLog, d: dict) -> dict:
    """Titre et lignes en langage simple pour UN événement du journal."""
    a, kind = r.action, KIND_OF[r.action]
    hours = f"{_hm(d.get('start'))}–{_hm(d.get('end'))}"
    who_from, who_to = _name(d.get("from")), _name(d.get("to"))
    lines: List[str] = []
    if a == "assignment.swap":
        A, B = d.get("a") or {}, d.get("b") or {}
        title = "Échange de shifts" + (_where(A) if _where(A) == _where(B) else "")
        lines = [f"{_name(A.get('from')) or '—'} ↔ {_name(A.get('to')) or '—'}",
                 f"{_name(A.get('to')) or '—'} prend {_day(A.get('day')) or '—'}, {_hm(A.get('start'))}–{_hm(A.get('end'))}{_where(A)}",
                 f"{_name(A.get('from')) or '—'} prend {_day(B.get('day')) or '—'}, {_hm(B.get('start'))}–{_hm(B.get('end'))}{_where(B)}"]
        return {"title": title, "lines": lines, "shift_days": sorted({x for x in (A.get("day"), B.get("day")) if x})}
    if kind == "hours":
        b, af = d.get("before") or {}, d.get("after") or {}
        names = ", ".join(e["name"] for e in d.get("employees", [])) or "Shift non attribué"
        if b:
            lines = [f"{names} : {_hm(b.get('start'))}–{_hm(b.get('end'))} → {_hm(af.get('start'))}–{_hm(af.get('end'))}"]
            if b.get("break_minutes") != af.get("break_minutes"):
                lines.append(f"Pause : {b.get('break_minutes')} min → {af.get('break_minutes')} min")
        else:  # ancien événement : seule la nouvelle valeur a été enregistrée
            lines = [f"Nouvel horaire : {hours} (horaire précédent {NOT_RECORDED})"]
        return {"title": "Modification d'horaires" + _where(d), "lines": lines}
    if kind == "replace":
        if who_from:
            lines = [f"{who_from} → {who_to or '—'}", f"Shift : {hours}"]
            return {"title": "Remplacement" + _where(d), "lines": lines}
        return {"title": "Attribution" + _where(d), "lines": [f"{who_to or '—'} : {hours}"]}
    if kind == "add":
        return {"title": ("Duplication" if a == "assignment.duplicate" else "Ajout d'un shift") + _where(d), "lines": [f"{who_to or '—'} : {hours}"]}
    if kind == "remove":
        why = f" ({d['reason']})" if a == "assignment.mission_release" and d.get("reason") else ""
        return {"title": "Suppression d'un shift" + _where(d), "lines": [f"{who_from or '—'} : {hours}{why}"]}
    if kind == "bulk":
        return {"title": "Modification groupée" + _where(d), "lines": [f"{who_from or '—'} → {who_to or '—'} : {hours}"]}
    if kind == "lock":
        return {"title": ("Verrouillage" if a == "assignment.lock" else "Déverrouillage") + _where(d), "lines": [f"{who_to or '—'} : {hours}"] if d else []}
    if kind == "generation":
        if a == "simulation.applied":
            return {"title": "Proposition appliquée au planning", "lines": [f"Version de sécurité n° {d['safety_version']} créée avant application" if d.get("safety_version") else "Planning remplacé par la proposition"]}
        label = "Réoptimisation partielle" if d.get("kind") in ("partial", "local") else "Génération du planning"
        n = d.get("assignments")
        lines = [f"{n} affectation(s) enregistrée(s)" + (f", {d['uncovered']} shift(s) non couvert(s)" if d.get("uncovered") else "")] if n is not None else []
        return {"title": label, "lines": lines}
    if kind == "restore":
        return {"title": f"Restauration de la version n° {d.get('number', '—')}", "lines": [f"{d.get('changed', 0)} affectation(s) modifiée(s)" + (f", version de sécurité n° {d['safety_version']}" if d.get("safety_version") else "")]}
    if kind == "publish":
        return {"title": f"Publication de la version n° {d.get('number', '—')}", "lines": [f"{d.get('notifications', 0)} collaborateur(s) prévenu(s)"]}
    if a == "period.deleted":
        by = d.get("by") or {}
        v = d.get("versions") or {}
        status = f" ({d['status_label'].lower()})" if d.get("status_label") else ""
        lines = [f"Planning de {d.get('label') or d.get('period') or '—'}{status} supprimé : {d.get('assignments', 0)} affectation(s) retirée(s) des vues actives",
                 f"Supprimé par {by.get('name') or NOT_RECORDED} (compte {by.get('id') or NOT_RECORDED})",
                 f"Conservé pour la traçabilité : archive des affectations, {v.get('total', 0)} version(s) et l'historique"]
        return {"title": "Suppression d'un planning", "lines": lines}
    if a == "version.create":
        return {"title": f"Version n° {d.get('number', '—')} enregistrée", "lines": [d["label"]] if d.get("label") else []}
    return {"title": f"Version n° {d.get('number', '—')} validée", "lines": []}


def _visible(r: m.AuditLog, d: dict) -> bool:
    if r.action == "optimization.finished":
        return bool(d.get("saved", d.get("status") in ("optimal", "faisable", "partiellement_couvert")))  # générations enregistrées seulement
    return True


def _employees(d: dict) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for part in (d, d.get("a") or {}, d.get("b") or {}):
        for k in ("from", "to"):
            x = part.get(k)
            if isinstance(x, dict) and x.get("id"):
                out[x["id"]] = x["name"]
    for e in d.get("employees", []):
        out[e["id"]] = e["name"]
    return out


@router.get("/history")
def history(ctx: Ctx = CtxDep, period_id: Optional[str] = None, employee_id: Optional[str] = None, site: Optional[str] = None,
            brand: Optional[str] = None, user_id: Optional[str] = None, kind: Optional[str] = None,
            date_from: Optional[date] = Query(None, alias="from"), date_to: Optional[date] = Query(None, alias="to"),
            before: Optional[datetime] = None, limit: int = Query(50, ge=1, le=200)):
    """Historique filtrable (période de modification, planning, collaborateur, site, marque, utilisateur, type d'action).
    Droits : tout le planning (planning.read) ; un responsable de marque ne voit que les événements de ses marques."""
    full = has_permission(ctx.user.role, "planning.read")
    if not full and not has_permission(ctx.user.role, "planning.brand"):
        raise HTTPException(403, "Permission requise : planning.read")
    scope = set((ctx.user.scope or {}).get("brands") or []) if not full else None
    if kind and kind not in KIND_LABEL:
        raise HTTPException(422, "Type d'action inconnu")
    tz = _tz(ctx)
    now = datetime.now(timezone.utc)
    q = select(m.AuditLog).where(m.AuditLog.action.in_(list(KIND_OF))).order_by(m.AuditLog.created_at.desc(), m.AuditLog.id)
    if date_from:
        q = q.where(m.AuditLog.created_at >= datetime.combine(date_from, time.min, tz))
    if date_to:
        q = q.where(m.AuditLog.created_at < datetime.combine(date_to + timedelta(days=1), time.min, tz))
    if before:
        q = q.where(m.AuditLog.created_at < before)
    if user_id:
        try:
            q = q.where(m.AuditLog.user_id == uuid.UUID(user_id))
        except ValueError:
            raise HTTPException(422, "Utilisateur inconnu")
    if kind:
        q = q.where(m.AuditLog.action.in_([a for a, k in KIND_OF.items() if k == kind]))
    rows = list(ctx.db.scalars(q.limit(3000)))
    users = {u.id: u.name for u in ctx.db.scalars(select(m.User))}
    # faits enregistrés ailleurs (jamais déduits) : planning d'une version, planning et auteur d'une génération
    versions = {str(v.id): v for v in ctx.db.scalars(select(m.ScheduleVersion))}
    runs = {str(x.id): x for x in ctx.db.scalars(select(m.OptimizationRun))}
    # un planning supprimé garde son nom, avec la mention de sa suppression : distinct d'un nouveau planning créé pour le même mois
    periods = {str(p.id): (f"{p.name} (planning supprimé le {p.deleted_at.astimezone(tz):%d/%m/%Y})" if p.deleted_at else p.name)
               for p in ctx.db.scalars(select(m.PlanningPeriod))}
    groups: "OrderedDict[tuple, dict]" = OrderedDict()
    last_at = None
    facets = {"users": {}, "employees": {}, "sites": {}, "brands": set()}
    for r in rows:
        d = dict(r.detail or {})
        if not _visible(r, d):
            continue
        author = r.user_id
        if r.entity == "version" and not d.get("period_id") and r.entity_id in versions:
            d["period_id"] = str(versions[r.entity_id].period_id)
        if r.entity == "run" and r.entity_id in runs:
            d.setdefault("period_id", str(runs[r.entity_id].period_id))
            author = author or runs[r.entity_id].requested_by
        pid = d.get("period_id") or ((d.get("a") or {}).get("period_id"))
        emps = _employees(d)
        brands = set(d.get("brands") or []) | set((d.get("a") or {}).get("brands") or []) | set((d.get("b") or {}).get("brands") or [])
        sites = {x for x in (d.get("site"), (d.get("a") or {}).get("site"), (d.get("b") or {}).get("site")) if x}
        site_names = {d.get("site"): d.get("site_name")} if d.get("site") else {}
        if scope is not None and not (brands & scope):
            continue  # responsable de marque : uniquement ses marques (un événement sans marque enregistrée n'est pas affiché)
        # choix proposés dans les filtres : calculés AVANT les filtres de contenu, pour pouvoir changer de choix
        for k, v in emps.items():
            facets["employees"][k] = v
        for s_ in sites:
            facets["sites"][s_] = site_names.get(s_) or facets["sites"].get(s_) or s_
        facets["brands"] |= brands
        if author:
            facets["users"][str(author)] = users.get(author, NOT_RECORDED)
        if (period_id and pid != period_id) or (employee_id and employee_id not in emps) or (site and site not in sites) or (brand and brand not in brands):
            continue
        key = (r.action, str(author), r.created_at) if r.action in GROUPED else (str(r.id),)
        part = {**_render(r, d), "shift_day": d.get("day"), "shift_day_label": _day(d.get("day"))}
        if key in groups:
            g = groups[key]
            g["details"].append(part)
            g["employees"].update(emps)
            g["brands"] |= brands
            g["sites"] |= sites
            if d.get("day"):
                g["shift_days"].add(d["day"])
            continue
        if len(groups) >= limit and r.created_at != last_at:
            continue  # page pleine : les choix des filtres restent complets ; jamais une même transaction coupée entre deux pages
        last_at = r.created_at
        groups[key] = {"id": str(r.id), "at": r.created_at, "action": r.action, "kind": KIND_OF[r.action], "author": author, "pid": pid, "part": part,
                       "details": [part], "employees": dict(emps), "brands": set(brands), "sites": set(sites),
                       "shift_days": set(part.get("shift_days") or ([d["day"]] if d.get("day") else [])), "forced": bool(d.get("forced")), "reason": d.get("reason")}
    items = []
    for g in groups.values():
        n = len(g["details"])
        days = sorted(g["shift_days"])
        if g["action"] in GROUPED and n > 1:
            title = {"assignment.bulk_transfer": "Modification groupée", "assignment.duplicate": "Duplication",
                     "assignment.mission_release": "Shifts libérés (mission)"}[g["action"]] + f" : {n} shifts" + (f" sur {' / '.join(sorted(g['brands']))}" if g["brands"] else "")
            lines = g["details"][0]["lines"][:1] + ([f"… et {n - 1} autre(s) (voir le détail)"] if n > 1 else [])
        else:
            title, lines = g["part"]["title"], g["part"]["lines"]
        items.append({
            "id": g["id"], "at": g["at"].isoformat(), "at_label": _when(g["at"], tz, now), "kind": g["kind"], "kind_label": KIND_LABEL[g["kind"]],
            "title": title, "lines": lines, "by": users.get(g["author"], NOT_RECORDED) if g["author"] else NOT_RECORDED,
            "period_id": g["pid"], "period": periods.get(g["pid"]) if g["pid"] else None,
            "shift_days": days, "shift_day_label": (_day(days[0]) if len(days) == 1 else f"du {_day(days[0])} au {_day(days[-1])}") if days else None,
            "employees": [{"id": k, "name": v} for k, v in g["employees"].items()], "brands": sorted(g["brands"]), "sites": sorted(g["sites"]),
            "forced": g["forced"], "reason": g["reason"], "details": g["details"] if n > 1 else [],
        })
    next_cursor = items[-1]["at"] if len(items) >= limit else None
    return {"timezone": tz.key, "items": items, "next": next_cursor,
            "facets": {"users": [{"id": k, "name": v} for k, v in sorted(facets["users"].items(), key=lambda kv: kv[1])],
                       "employees": [{"id": k, "name": v} for k, v in sorted(facets["employees"].items(), key=lambda kv: kv[1])],
                       "sites": [{"code": k, "name": v} for k, v in sorted(facets["sites"].items(), key=lambda kv: kv[1])],
                       "brands": sorted(facets["brands"])},
            "kinds": [{"key": k, "label": v} for k, v in KIND_LABEL.items()]}
