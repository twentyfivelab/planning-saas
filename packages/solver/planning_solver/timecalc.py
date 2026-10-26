"""Calculs de temps fiables, côté serveur, en Europe/Zurich.

Distingue présence sur site, pause non travaillée et travail effectif.
Les calculs passent par des datetimes avec fuseau (gestion du changement d'heure).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Zurich")


@dataclass(frozen=True)
class ShiftHours:
    presence_minutes: int
    break_minutes: int
    effective_minutes: int

    @property
    def presence_hours(self) -> float:
        return self.presence_minutes / 60

    @property
    def effective_hours(self) -> float:
        return self.effective_minutes / 60


def localize(d: date, t: time) -> datetime:
    return datetime.combine(d, t, tzinfo=TZ)


def shift_bounds(d: date, start: time, end: time) -> "tuple[datetime, datetime]":
    """Début/fin aware ; si end <= start le shift se termine le lendemain."""
    s = localize(d, start)
    e = localize(d if end > start else d + timedelta(days=1), end)
    return s, e


def shift_hours(d: date, start: time, end: time, break_minutes: int) -> ShiftHours:
    if break_minutes < 0:
        raise ValueError("break_minutes must be >= 0")
    s, e = shift_bounds(d, start, end)
    presence = int((e.astimezone(timezone.utc) - s.astimezone(timezone.utc)).total_seconds() // 60)
    if break_minutes > presence:
        raise ValueError("La pause dépasse la présence")
    return ShiftHours(presence, break_minutes, presence - break_minutes)


def split_allocation(effective_minutes: int, shares: "dict[str, float]") -> "dict[str, int]":
    """Ventile les minutes effectives d'UNE affectation entre budgets.

    Les parts sont normalisées ; la somme des imputations == minutes effectives
    (les heures du collaborateur ne sont jamais doublées).
    """
    total = sum(shares.values())
    if total <= 0:
        raise ValueError("Parts invalides")
    out = {k: int(effective_minutes * v / total) for k, v in shares.items()}
    rest = effective_minutes - sum(out.values())
    for k in list(out)[:rest]:
        out[k] += 1
    return out
