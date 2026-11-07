"""Détail d'audit homogène des modifications manuelles du planning (qui remplace qui, quand, par qui)."""
from . import models as m


def assignment_detail(db, sh: m.Shift, from_emp, to_emp, **extra) -> dict:
    """Noms et horaires figés au moment de la modification : l'historique reste lisible même si le collaborateur est renommé."""
    emp = lambda e: {"id": str(e.id), "name": e.name} if e is not None else None  # noqa: E731
    ids = [str(e.id) for e in (from_emp, to_emp) if e is not None]
    return {"period_id": str(sh.period_id), "shift_id": str(sh.id), "slot_key": sh.slot_key, "day": sh.day.isoformat(),
            "site": sh.site_code, "start": sh.start_time.isoformat(), "end": sh.end_time.isoformat(),
            "from": emp(from_emp), "to": emp(to_emp), "employee_ids": ids, **extra}
