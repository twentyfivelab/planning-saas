"""Données de démonstration novembre 2026 : python -m app.seed
Les mots de passe ne sont jamais codés en dur : DEMO_PASSWORD (env) ou généré et affiché une fois."""
import secrets
import uuid
from datetime import date

from . import models as m
from .config import settings
from .db import tenant_session
from .security import hash_password

from planning_solver import demo_nov2026 as demo


def seed(tenant_name: str = "Démo Retail Genève", domain: str = "demo.example") -> dict:
    if settings.app_env not in ("development", "test"):
        raise RuntimeError("Seed de démonstration refusé : APP_ENV doit valoir 'development' ou 'test' "
                           "(aucun compte de démonstration ne doit exister en production).")
    pw = settings.demo_password or secrets.token_urlsafe(16)
    tid = uuid.uuid4()
    month = date(2026, 11, 1)
    with tenant_session(str(tid)) as db:
        db.add(m.Tenant(id=tid, name=tenant_name))
        db.flush()
        db.add(m.Subscription(tenant_id=tid, plan="trial"))
        for role, email in (("owner", "owner"), ("manager", "manager"), ("planner", "planner"),
                            ("auditor", "auditor"), ("employee", "collaborateur")):
            db.add(m.User(tenant_id=tid, email=f"{email}@{domain}", name=role.capitalize(), role=role,
                          password_hash=hash_password(pw)))
        db.add(m.PlanningPeriod(tenant_id=tid, name="Novembre 2026", start_date=demo.START, end_date=demo.END))
        operating = {"Valmont": [0, 2, 3, 4, 5], "Cellcosmet": [0, 1, 3, 4, 5], "Nuxe": [0, 1, 3, 4, 5],
                     "Cailler": [0, 1, 2, 3, 4, 5], "Cartier": [4, 5]}
        for b in demo.BUDGET_HOURS:
            code = b
            db.add(m.Brand(tenant_id=tid, code=code, name=code, active_weekdays=operating.get(b, list(range(7))), group_code=(
                "COSMETIQUE" if b in ("Valmont", "Cellcosmet", "Nuxe") else None)))
            db.add(m.MonthlyBudget(tenant_id=tid, brand_code=code, month=month,
                                   target_minutes=demo.BUDGET_HOURS[b] * 60,
                                   requirements_defined=b not in ("Lindt", "Toblerone")))
        for code in ("GVA3", "GVA9", "Cartier", "Valmont", "Nuxe/Cellcosmet", "Cailler"):
            db.add(m.Site(tenant_id=tid, code=code, name=code))
        db.flush()
        # modèles et besoins (dérivés du jeu de démonstration, mêmes horaires)
        tpl = {}
        for s in {(x.template_id, x.start, x.end, x.tag) for x in demo.build_slots()}:
            t = m.ShiftTemplate(tenant_id=tid, code=s[0], start_time=s[1], end_time=s[2], break_minutes=60,
                                tag=s[3], is_hypothesis=s[0] in demo.HYPOTHETICAL_TEMPLATES,
                                hypothesis_note=demo.HYPOTHETICAL_TEMPLATES.get(s[0]))
            db.add(t)
            tpl[s[0]] = t
        db.flush()
        seen = {}
        for x in demo.build_slots():
            key = x.id.split("|")[0] + "-" + x.template_id
            r = seen.get(key)
            if r is None:
                r = dict(code=key, template=x.template_id, site=x.site, alloc={b: 1 for b in x.allocations},
                         days=set(), mandatory=x.mandatory, flex=(x.day_group or "").split("|")[0] or None,
                         stagger=x.stagger_group)
                seen[key] = r
            r["days"].add(x.day.weekday())
        for r in seen.values():
            db.add(m.StaffingRequirement(
                tenant_id=tid, code=r["code"], template_id=tpl[r["template"]].id, site_code=r["site"],
                allocations=r["alloc"], weekdays=sorted(r["days"]), mandatory=r["mandatory"],
                flex_group=r["flex"], stagger_group=r["stagger"]))
        emps = {}
        for e in demo.build_employees():
            row = m.Employee(tenant_id=tid, code=e.id, name=e.name, brands=e.brands, allocation_weight=e.weight)
            db.add(row)
            emps[e.id] = row
        db.flush()
        for e in demo.build_employees():
            row = emps[e.id]
            for wd in e.unavailable_weekdays:
                db.add(m.Unavailability(tenant_id=tid, employee_id=row.id, weekday=wd, reason="indisponibilité fournie"))
            for wd in sorted(e.available_weekdays or ()):
                db.add(m.Availability(tenant_id=tid, employee_id=row.id, weekday=wd))
            if e.forbidden_tags:
                db.add(m.ConstraintDefinition(tenant_id=tid, kind="internal", code="forbidden_tag", scope="employee",
                                              employee_id=row.id, params={"tags": sorted(e.forbidden_tags)}))
            if e.max_days_per_week:
                db.add(m.ConstraintDefinition(tenant_id=tid, kind="internal", code="max_days_per_week",
                                              scope="employee", employee_id=row.id,
                                              params={"value": e.max_days_per_week}))
            if e.latest_start:
                db.add(m.EmployeePreference(tenant_id=tid, employee_id=row.id, kind="latest_start",
                                            params={"time": e.latest_start.strftime("%H:%M")}))
            if e.preferred_times:
                db.add(m.EmployeePreference(tenant_id=tid, employee_id=row.id, kind="preferred_times",
                                            params={"times": [[a.strftime("%H:%M"), b.strftime("%H:%M")]
                                                              for a, b in sorted(e.preferred_times)]}))
            if e.preferred_tags:
                db.add(m.EmployeePreference(tenant_id=tid, employee_id=row.id, kind="preferred_tags",
                                            params={"tags": sorted(e.preferred_tags)},
                                            strength=e.preference_strength))
            if e.weekly_rest_days_pref:
                db.add(m.EmployeePreference(tenant_id=tid, employee_id=row.id, kind="weekly_rest_days",
                                            params={"days": e.weekly_rest_days_pref}, strength=3,
                                            is_hard=e.weekly_rest_days_hard))
        for a, b in (("mila", "abdu"), ("abdu", "mila")):
            db.add(m.RelationshipPreference(tenant_id=tid, employee_id=emps[a].id, other_employee_id=emps[b].id,
                                            note="mariés, un enfant : horaires opposés (préférence souple)"))
        for code, val, note in (("rest_hours", 11, "Valeur de référence initiale"),
                                ("max_consecutive_days", 6, "Plafond interne initial")):
            db.add(m.ConstraintDefinition(tenant_id=tid, kind="internal" if code != "rest_hours" else "legal",
                                          code=code, params={"value": val}, jurisdiction="CH",
                                          legal_review_status="a_valider", exception_reason=note))
        # Aucun contrat n'est créé : ils ne sont pas fournis.
    return {"tenant_id": str(tid), "password": pw if not settings.demo_password else "(DEMO_PASSWORD)",
            "accounts": [f"{r}@{domain}" for r in ("owner", "manager", "planner", "auditor", "collaborateur")]}


if __name__ == "__main__":
    import sys
    out = seed(domain=sys.argv[1] if len(sys.argv) > 1 else "demo.example")
    print("Tenant:", out["tenant_id"])
    print("Comptes:", ", ".join(out["accounts"]))
    print("Mot de passe (affiché une seule fois):", out["password"])
