"""Rôles et permissions (source unique ; synchronisée en base par la migration)."""
PERMISSIONS = [
    "tenant.manage", "users.manage", "referential.read", "referential.write", "employees.read",
    "employees.write", "contracts.write", "availability.write", "rules.write", "budgets.write",
    "planning.read", "planning.brand", "planning.edit", "planning.optimize", "planning.publish", "planning.validate", "audit.read", "export.run",
    "import.run", "self.read", "time.write", "time.validate", "reports.read", "finance.read", "legal.review", "planning.admin",
    "planning.delete",  # suppression d'un planning généré (confirmée par mot de passe) : propriétaire et administrateur
]
_RO = {"referential.read", "employees.read", "planning.read", "planning.brand", "audit.read", "export.run", "reports.read"}
_PLAN = _RO | {"referential.write", "employees.write", "contracts.write", "availability.write", "rules.write",
               "budgets.write", "planning.edit", "planning.optimize", "planning.publish", "import.run", "time.write"}
ROLES = {
    "owner": ("Propriétaire", set(PERMISSIONS)),
    "admin": ("Administrateur", set(PERMISSIONS) - {"tenant.manage"}),
    "manager": ("Manager", _PLAN | {"audit.read", "planning.validate", "time.validate", "finance.read", "self.read"}),
    "planner": ("Planificateur", (_PLAN - {"planning.publish", "audit.read"}) | {"self.read"}),
    # « planning.brand » : planning limité aux marques du périmètre (users.scope) ; « planning.read » : tout le planning du tenant
    "brand_manager": ("Responsable de marque", {"planning.brand", "referential.read", "reports.read", "time.validate", "self.read"}),
    "employee": ("Collaborateur", {"self.read"}),  # uniquement son planning publié (/me/planning) et ses notifications
    "auditor": ("Lecture seule / auditeur", _RO | {"self.read"}),
}


def has_permission(role: str, perm: str) -> bool:
    return perm in ROLES.get(role, ("", set()))[1]
