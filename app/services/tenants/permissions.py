"""Static catalog of all permission slugs and the role → permission matrix.

Pure data, no logic. The migration `20260509_0024_*` is the source of truth
for what gets seeded into existing tenant DBs; this module is the source of
truth for what gets seeded into NEW tenant DBs by `provisioning.seed_tenant_data`.

Keep the two in sync — `tests/test_tenant_service.py::test_role_permissions_reference_valid_slugs`
guards against drift inside this file but cannot detect missing migrations.
"""

from typing import Any

ALL_PERMISSIONS: list[dict[str, str]] = [
    # Admin module (28)
    {"slug": "admin:students:read", "name": "View students"},
    {"slug": "admin:students:create", "name": "Create students"},
    {"slug": "admin:students:update", "name": "Update students"},
    {"slug": "admin:students:delete", "name": "Delete students"},
    {"slug": "admin:teachers:read", "name": "View teachers"},
    {"slug": "admin:teachers:create", "name": "Create teachers"},
    {"slug": "admin:teachers:update", "name": "Update teachers"},
    {"slug": "admin:teachers:delete", "name": "Delete teachers"},
    {"slug": "admin:staff:read", "name": "View staff"},
    {"slug": "admin:staff:create", "name": "Create staff"},
    {"slug": "admin:staff:update", "name": "Update staff"},
    {"slug": "admin:staff:delete", "name": "Delete staff"},
    {"slug": "admin:classes:read", "name": "View classes"},
    {"slug": "admin:classes:create", "name": "Create classes"},
    {"slug": "admin:classes:update", "name": "Update classes"},
    {"slug": "admin:classes:delete", "name": "Delete classes"},
    {"slug": "admin:subjects:read", "name": "View subjects"},
    {"slug": "admin:subjects:create", "name": "Create subjects"},
    {"slug": "admin:subjects:update", "name": "Update subjects"},
    {"slug": "admin:subjects:delete", "name": "Delete subjects"},
    {"slug": "admin:academic-years:read", "name": "View academic years"},
    {"slug": "admin:academic-years:create", "name": "Create academic years"},
    {"slug": "admin:academic-years:update", "name": "Update academic years"},
    {"slug": "admin:academic-years:delete", "name": "Delete academic years"},
    {"slug": "admin:levels:read", "name": "View levels"},
    {"slug": "admin:levels:create", "name": "Create levels"},
    {"slug": "admin:levels:update", "name": "Update levels"},
    {"slug": "admin:levels:delete", "name": "Delete levels"},
    {"slug": "admin:fee-categories:read", "name": "View fee categories"},
    {"slug": "admin:fee-categories:create", "name": "Create fee categories"},
    {"slug": "admin:fee-categories:update", "name": "Update fee categories"},
    {"slug": "admin:fee-categories:delete", "name": "Delete fee categories"},
    {"slug": "admin:fee-variants:read", "name": "View fee variants"},
    {"slug": "admin:fee-variants:create", "name": "Create fee variants"},
    {"slug": "admin:fee-variants:update", "name": "Update fee variants"},
    {"slug": "admin:fee-variants:delete", "name": "Delete fee variants"},
    {"slug": "admin:fee-options:read", "name": "View fee options"},
    {"slug": "admin:fee-options:create", "name": "Create fee options"},
    {"slug": "admin:fee-options:update", "name": "Update fee options"},
    {"slug": "admin:fee-options:delete", "name": "Delete fee options"},
    # Academic (8)
    {"slug": "enrollments:read", "name": "View enrollments"},
    {"slug": "enrollments:create", "name": "Create enrollments"},
    {"slug": "enrollments:update", "name": "Update enrollments"},
    {"slug": "enrollments:delete", "name": "Delete enrollments"},
    {"slug": "enrollments:promote", "name": "Mass-promote enrollments year over year"},
    {"slug": "grades:read", "name": "View grades"},
    {"slug": "grades:write", "name": "Write grades"},
    {"slug": "bulletins:generate", "name": "Generate bulletins"},
    # Timetable (3)
    {"slug": "timetable:read", "name": "View timetable"},
    {"slug": "timetable:write", "name": "Edit timetable"},
    {"slug": "timetable:generate", "name": "Generate timetable"},
    # Operations (5)
    {"slug": "payments:read", "name": "View payments"},
    {"slug": "payments:create", "name": "Create payments"},
    {"slug": "attendance:read", "name": "View attendance"},
    {"slug": "attendance:create", "name": "Create attendance"},
    {"slug": "attendance:update", "name": "Update attendance"},
    # Reports (3)
    {"slug": "reports:read", "name": "View reports"},
    {"slug": "reports:generate", "name": "Generate reports"},
    {"slug": "reports:override", "name": "Override council decisions"},
    # Teacher attendance (Phase 7b) (3)
    {"slug": "admin:teachers:attendance", "name": "Manage teacher attendance"},
    {"slug": "admin:teachers:attendance:read", "name": "View teacher attendance"},
    {"slug": "teacher:attendance:self_declare", "name": "Teacher self-declare absence"},
    # Official documents (2)
    {"slug": "documents:certificate", "name": "Generate certificat de scolarite"},
    {"slug": "documents:attendance", "name": "Generate attestation de frequentation"},
    # Parents (4)
    {"slug": "admin:parents:read", "name": "View parents"},
    {"slug": "admin:parents:create", "name": "Create parents"},
    {"slug": "admin:parents:update", "name": "Update parents"},
    {"slug": "admin:parents:delete", "name": "Delete parents"},
    # Roles & Permissions management (2)
    {"slug": "admin:roles:read", "name": "View roles and permissions"},
    {"slug": "admin:roles:write", "name": "Manage roles and permissions"},
    # Rooms (4)
    {"slug": "admin:rooms:read", "name": "View rooms"},
    {"slug": "admin:rooms:create", "name": "Create rooms"},
    {"slug": "admin:rooms:update", "name": "Update rooms"},
    {"slug": "admin:rooms:delete", "name": "Delete rooms"},
    # Series (2)
    {"slug": "admin:series:read", "name": "View academic series"},
    {"slug": "admin:series:write", "name": "Manage academic series"},
    # Super Admin (7)
    {"slug": "super-admin:tenants:create", "name": "Provision new tenants"},
    {"slug": "super-admin:tenants:read", "name": "View tenants list and per-tenant stats"},
    {"slug": "super-admin:tenants:status:write", "name": "Suspend / restore / archive a tenant"},
    {"slug": "super-admin:diagnose:read", "name": "Run platform and per-tenant diagnostics"},
    {"slug": "super-admin:logs:read", "name": "Read system logs (with redaction)"},
    {"slug": "super-admin:db:execute", "name": "Execute raw SQL queries against any tenant DB"},
    {"slug": "super-admin:pats:manage", "name": "Create / list / revoke personal access tokens"},
]


_SUPER_ADMIN_PERMS = [p["slug"] for p in ALL_PERMISSIONS if p["slug"].startswith("super-admin:")]


ROLE_DEFINITIONS: dict[str, dict[str, Any]] = {
    "admin": {
        "description": "Administrateur — accès complet du tenant",
        "permissions": [
            p["slug"] for p in ALL_PERMISSIONS if not p["slug"].startswith("super-admin:")
        ],
    },
    "director": {
        "description": "Directeur d'établissement",
        "permissions": [
            p["slug"] for p in ALL_PERMISSIONS if not p["slug"].startswith("super-admin:")
        ],
    },
    "teacher": {
        "description": "Enseignant",
        "permissions": [
            "grades:read",
            "grades:write",
            "bulletins:generate",
            "attendance:read",
            "attendance:create",
            "attendance:update",
            "timetable:read",
            "reports:read",
            "teacher:attendance:self_declare",
        ],
    },
    "staff": {
        "description": "Personnel administratif",
        "permissions": [
            "enrollments:read",
            "enrollments:create",
            "enrollments:update",
            "payments:read",
            "payments:create",
            "admin:students:read",
            "admin:students:create",
            "admin:students:update",
            "admin:classes:read",
            "attendance:read",
            "reports:read",
            "admin:teachers:attendance",
            "admin:teachers:attendance:read",
        ],
    },
    "accountant": {
        "description": "Comptable / Trésorier",
        "permissions": [
            "payments:read",
            "payments:create",
            "enrollments:read",
            "reports:read",
        ],
    },
    "student": {
        "description": "Élève — accès portail élève uniquement",
        "permissions": [],
    },
    "parent": {
        "description": "Parent / Tuteur — accès portail parent uniquement",
        "permissions": [],
    },
    "super_admin": {
        "description": "Super Administrateur — operations multi-tenant et plateforme",
        "permissions": _SUPER_ADMIN_PERMS,
    },
}
# Note: student and parent roles have NO permissions (portal is user-scoped via JWT)
