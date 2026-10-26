"""Rôles et permissions (source unique ; synchronisée en base par la migration)."""
PERMISSIONS = [
    "tenant.manage", "users.manage", "referential.read", "referential.write", "employees.read",
    "employees.write", "contracts.write", "availability.write", "rules.write", "budgets.write",
    "planning.read", "planning.edit", "planning.optimize", "planning.publish", "audit.read", "export.run",
    "import.run", "self.read",
]
_RO = {"referential.read", "employees.read", "planning.read", "audit.read", "export.run"}
_PLAN = _RO | {"referential.write", "employees.write", "contracts.write", "availability.write", "rules.write",
               "budgets.write", "planning.edit", "planning.optimize", "planning.publish", "import.run"}
ROLES = {
    "owner": ("Propriétaire", set(PERMISSIONS)),
    "admin": ("Administrateur", set(PERMISSIONS) - {"tenant.manage"}),
    "manager": ("Manager", _PLAN | {"audit.read"}),
    "planner": ("Planificateur", _PLAN - {"planning.publish", "audit.read"}),
    "employee": ("Collaborateur", {"planning.read", "self.read"}),
    "auditor": ("Lecture seule / auditeur", _RO),
}


def has_permission(role: str, perm: str) -> bool:
    return perm in ROLES.get(role, ("", set()))[1]
