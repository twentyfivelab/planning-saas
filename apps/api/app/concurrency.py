"""Modifications simultanées : jamais d'écrasement silencieux du travail d'un autre utilisateur.

Le navigateur envoie ce qu'il AFFICHAIT (titulaire, horaires) ; le serveur verrouille la ligne (même ordre partout : shift, puis
affectation) et refuse avec un message compréhensible si elle a changé entre-temps. Rien n'est alors modifié ; l'écran recharge."""
import uuid
from datetime import time
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select

from . import models as m

STALE = "Ce shift vient d'être modifié par quelqu'un d'autre. Le planning a été actualisé : vérifiez la nouvelle situation puis recommencez. Rien n'a été modifié."
GONE = "Ce shift a déjà été retiré ou remplacé par quelqu'un d'autre. Le planning a été actualisé. Rien n'a été modifié."


def stale(message: str = STALE) -> HTTPException:
    return HTTPException(409, detail={"code": "stale", "can_override": False, "issues": [], "message": message})


def _uuid(x) -> Optional[uuid.UUID]:
    try:
        return uuid.UUID(str(x))
    except (ValueError, TypeError):
        return None


def lock_assignment(db, aid) -> m.Assignment:
    """Affectation verrouillée pour la durée de la transaction (shift d'abord, comme toute autre modification de ce shift)."""
    key = _uuid(aid)
    a0 = db.get(m.Assignment, key) if key else None
    if a0 is None:
        raise HTTPException(404, detail={"code": "gone", "message": GONE})
    db.execute(select(m.Shift.id).where(m.Shift.id == a0.shift_id).with_for_update())
    a = db.execute(select(m.Assignment).where(m.Assignment.id == key).with_for_update().execution_options(populate_existing=True)).scalar_one_or_none()
    if a is None:
        raise HTTPException(404, detail={"code": "gone", "message": GONE})
    return a


def check_holder(a: m.Assignment, expected) -> None:
    """`expected` : titulaire affiché à l'écran (identifiant), ou None si l'écran ne l'a pas transmis (ancien client)."""
    if expected is not None and str(a.employee_id) != str(expected):
        raise stale()


def lock_shift(db, sid) -> m.Shift:
    key = _uuid(sid)
    sh = db.execute(select(m.Shift).where(m.Shift.id == key).with_for_update().execution_options(populate_existing=True)).scalar_one_or_none() if key else None
    if sh is None:
        raise HTTPException(404, detail={"code": "gone", "message": GONE})
    return sh


def check_times(sh: m.Shift, start: Optional[time], end: Optional[time], brk: Optional[int]) -> None:
    if (start is not None and sh.start_time != start) or (end is not None and sh.end_time != end) or (brk is not None and sh.break_minutes != brk):
        raise stale("Les horaires de ce shift viennent d'être modifiés par quelqu'un d'autre. Le planning a été actualisé : vérifiez puis recommencez. Rien n'a été modifié.")
