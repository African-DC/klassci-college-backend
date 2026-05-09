"""Add super_admin role + cross-tenant operations permissions.

Extends `users.role` enum with 'super_admin', seeds 6 new permissions
(super-admin:tenants:read, status:write, diagnose:read, logs:read,
db:execute, pats:manage), creates the super_admin role and links every
super-admin:* permission to it.

The `super-admin:tenants:create` slug already exists from the initial
seed and is preserved.

Revision ID: 0024
Revises: 0023
Create Date: 2026-05-09
"""

from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


_NEW_PERMISSIONS = [
    ("super-admin:tenants:read", "View tenants list and per-tenant stats"),
    ("super-admin:tenants:status:write", "Suspend / restore / archive a tenant"),
    ("super-admin:diagnose:read", "Run platform and per-tenant diagnostics"),
    ("super-admin:logs:read", "Read system logs (with redaction)"),
    ("super-admin:db:execute", "Execute raw SQL queries against any tenant DB"),
    ("super-admin:pats:manage", "Create / list / revoke personal access tokens"),
]

_NEW_ROLE = (
    "super_admin",
    "Super Administrateur — operations multi-tenant et plateforme",
)

_USER_ROLE_VALUES_NEW = "'admin','teacher','staff','student','parent','super_admin'"
_USER_ROLE_VALUES_OLD = "'admin','teacher','staff','student','parent'"


def upgrade() -> None:
    op.execute(f"ALTER TABLE users MODIFY COLUMN role ENUM({_USER_ROLE_VALUES_NEW}) NOT NULL")

    perms_values = ", ".join(f"('{slug}', '{name}')" for slug, name in _NEW_PERMISSIONS)
    op.execute(f"INSERT IGNORE INTO permissions (slug, name) VALUES {perms_values}")

    op.execute(
        f"INSERT IGNORE INTO roles (name, description) "
        f"VALUES ('{_NEW_ROLE[0]}', '{_NEW_ROLE[1]}')"
    )

    op.execute(
        """
        INSERT IGNORE INTO role_permissions (role_id, permission_id)
        SELECT r.id, p.id
        FROM roles r
        CROSS JOIN permissions p
        WHERE r.name = 'super_admin'
        AND p.slug LIKE 'super-admin:%'
        """
    )


def downgrade() -> None:
    new_slugs = ", ".join(f"'{slug}'" for slug, _ in _NEW_PERMISSIONS)

    op.execute(
        "DELETE rp FROM role_permissions rp "
        "JOIN roles r ON rp.role_id = r.id "
        "WHERE r.name = 'super_admin'"
    )
    op.execute("DELETE FROM roles WHERE name = 'super_admin'")
    op.execute(f"DELETE FROM permissions WHERE slug IN ({new_slugs})")
    op.execute(f"ALTER TABLE users MODIFY COLUMN role ENUM({_USER_ROLE_VALUES_OLD}) NOT NULL")
