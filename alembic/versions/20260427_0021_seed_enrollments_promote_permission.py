"""Seed `enrollments:promote` permission for the bulk year rollover endpoint.

Cycle 3 plan B introduit `POST /admin/promotions/preview` et
`POST /admin/promotions/execute` qui require_permission("enrollments:promote").
Sans cette migration, les tenants existants verraient un 403 silencieux sur
ces endpoints (cf. memory feedback_permission_seed_audit).

Revision ID: 0021
Revises: 0020
Create Date: 2026-04-27
"""

from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


_PERMISSION_SLUG = "enrollments:promote"
_PERMISSION_NAME = "Mass-promote enrollments year over year"


def upgrade() -> None:
    op.execute(
        f"INSERT IGNORE INTO permissions (slug, name) "
        f"VALUES ('{_PERMISSION_SLUG}', '{_PERMISSION_NAME}')"
    )
    op.execute(
        f"""
        INSERT IGNORE INTO role_permissions (role_id, permission_id)
        SELECT r.id, p.id
        FROM roles r
        CROSS JOIN permissions p
        WHERE r.name IN ('admin', 'director')
        AND p.slug = '{_PERMISSION_SLUG}'
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        DELETE rp FROM role_permissions rp
        JOIN permissions p ON rp.permission_id = p.id
        WHERE p.slug = '{_PERMISSION_SLUG}'
        """
    )
    op.execute(f"DELETE FROM permissions WHERE slug = '{_PERMISSION_SLUG}'")
