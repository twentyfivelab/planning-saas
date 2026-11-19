"""Budget du mois prérempli depuis le budget de base de chaque marque.

Règles : un NOUVEAU mois (brouillon jamais généré) reçoit, pour chaque marque qui a un budget de base et n'a pas encore de budget ce
mois-là, ce budget de base. Une seule fois par marque et par planning (`budget_init`) : un ajustement ultérieur, y compris un champ
vidé, n'est jamais écrasé. Un planning déjà généré ou calculé n'est jamais prérempli. Les autres mois ne sont jamais touchés."""
from sqlalchemy import func, select

from . import models as m


def init_budgets_from_base(db, tenant_id, period: m.PlanningPeriod, user_id=None) -> list:
    info = dict(period.budget_init or {})
    if info.get("legacy") or period.deleted_at is not None:
        return []
    generated = db.scalar(select(func.count()).select_from(m.Assignment).where(m.Assignment.period_id == period.id)) or \
        db.scalar(select(func.count()).select_from(m.OptimizationRun).where(m.OptimizationRun.period_id == period.id))
    if generated:
        return []
    first = period.start_date.replace(day=1)
    done = set(info.get("brands") or [])
    existing = {b.brand_code for b in db.scalars(select(m.MonthlyBudget).where(m.MonthlyBudget.month == first))}
    created = []
    for b in db.scalars(select(m.Brand).where(m.Brand.base_budget_minutes.is_not(None))):
        if b.code in done or (b.archived_from and b.archived_from <= first):
            continue
        if b.code not in existing:
            db.add(m.MonthlyBudget(tenant_id=tenant_id, brand_code=b.code, month=first, target_minutes=b.base_budget_minutes, strict=True))
            created.append({"brand": b.code, "minutes": b.base_budget_minutes})
        done.add(b.code)  # marque traitée, même si un budget existait déjà : plus jamais modifiée par le préremplissage
    if done != set(info.get("brands") or []):
        period.budget_init = {**info, "brands": sorted(done)}
    if created:
        db.flush()
        db.add(m.AuditLog(tenant_id=tenant_id, user_id=user_id, action="budget.init_from_base", entity="period", entity_id=str(period.id),
                          detail={"period": period.name, "month": first.isoformat(), "created": created}))
    return created
