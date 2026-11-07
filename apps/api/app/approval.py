"""Qui peut approuver une dérogation : un rôle d'encadrement, jamais la personne concernée elle-même."""
from typing import Iterable, Optional

OVERRIDE_ROLES = ("owner", "admin", "manager")


def override_refusal(ctx, concerned: Iterable) -> Optional[str]:
    """None si l'utilisateur peut approuver la dérogation ; sinon le motif du refus (affiché tel quel)."""
    if ctx.user.role not in OVERRIDE_ROLES:
        return "Seul un propriétaire, un administrateur ou un manager peut approuver une dérogation : demandez-lui de valider."
    if ctx.user.employee_id is not None and ctx.user.employee_id in {c for c in concerned if c is not None}:
        return "Vous ne pouvez pas approuver une dérogation qui vous concerne : un autre responsable doit la valider."
    return None
