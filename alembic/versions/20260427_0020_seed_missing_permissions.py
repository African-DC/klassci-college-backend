"""Seed permissions referenced by routers but missing from initial seed.

Routers reference 8 permission slugs that were never added to ALL_PERMISSIONS,
which caused 403 silently for any user trying to access roles/rooms/series UIs.

Revision ID: 0020
Revises: 0019
Create Date: 2026-04-27
"""
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


_NEW_PERMISSIONS = [
    ("admin:roles:read", "View roles and permissions"),
    ("admin:roles:write", "Manage roles and permissions"),
    ("admin:rooms:read", "View rooms"),
    ("admin:rooms:create", "Create rooms"),
    ("admin:rooms:update", "Update rooms"),
    ("admin:rooms:delete", "Delete rooms"),
    ("admin:series:read", "View academic series"),
    ("admin:series:write", "Manage academic series"),
]


def upgrade() -> None:
    values_sql = ", ".join(f"('{slug}', '{name}')" for slug, name in _NEW_PERMISSIONS)
    op.execute(f"INSERT IGNORE INTO permissions (slug, name) VALUES {values_sql}")

    slugs_sql = ", ".join(f"'{slug}'" for slug, _ in _NEW_PERMISSIONS)
    op.execute(
        f"""
        INSERT IGNORE INTO role_permissions (role_id, permission_id)
        SELECT r.id, p.id
        FROM roles r
        CROSS JOIN permissions p
        WHERE r.name IN ('admin', 'director')
        AND p.slug IN ({slugs_sql})
        """
    )


def downgrade() -> None:
    slugs_sql = ", ".join(f"'{slug}'" for slug, _ in _NEW_PERMISSIONS)
    op.execute(
        f"""
        DELETE rp FROM role_permissions rp
        JOIN permissions p ON rp.permission_id = p.id
        WHERE p.slug IN ({slugs_sql})
        """
    )
    op.execute(f"DELETE FROM permissions WHERE slug IN ({slugs_sql})")
