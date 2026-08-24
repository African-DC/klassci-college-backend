"""Seed permission `performance:read` (score de performance enseignant/personnel).

La vue direction `/admin/performance/*` est gardée par `performance:read`,
accordée à `admin` et `director`. La vue enseignant `/teacher/performance/me`
n'a pas besoin de permission (scopée au JWT, données propres uniquement).

Revision ID: 0034_performance_perm
Revises: 0033_school_holidays
Create Date: 2026-07-03
"""

from alembic import op

revision = "0034_performance_perm"
down_revision = "0033_school_holidays"
branch_labels = None
depends_on = None


_NEW_PERMISSIONS = [
    ("performance:read", "View teacher and staff performance"),
]


_ROLE_PERMISSION_MATRIX = {
    "admin": ["performance:read"],
    "director": ["performance:read"],
}


def upgrade() -> None:
    values_sql = ", ".join(f"('{slug}', '{name}')" for slug, name in _NEW_PERMISSIONS)
    op.execute(f"INSERT IGNORE INTO permissions (slug, name) VALUES {values_sql}")

    for role_name, slugs in _ROLE_PERMISSION_MATRIX.items():
        slugs_sql = ", ".join(f"'{slug}'" for slug in slugs)
        op.execute(
            f"""
            INSERT IGNORE INTO role_permissions (role_id, permission_id)
            SELECT r.id, p.id
            FROM roles r
            CROSS JOIN permissions p
            WHERE r.name = '{role_name}'
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
