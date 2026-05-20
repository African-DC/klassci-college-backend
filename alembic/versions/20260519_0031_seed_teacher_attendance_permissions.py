"""Seed teacher attendance permissions (Phase 7b finition).

Phase 7b a livré le BE foundation (model + service + endpoints) en migration
0030 mais les permissions n'avaient pas encore été seedées. Sans ces 3 slugs,
les endpoints retournent 403 même pour admin/staff/teacher légitimes.

- admin:teachers:attendance        → admin, director, staff
- admin:teachers:attendance:read   → admin, director, staff
- teacher:attendance:self_declare  → admin, director, teacher

Revision ID: 0031_teacher_attendance_perms
Revises: 0030_teacher_attendance
Create Date: 2026-05-19
"""

from alembic import op

revision = "0031_teacher_attendance_perms"
down_revision = "0030_teacher_attendance"
branch_labels = None
depends_on = None


_NEW_PERMISSIONS = [
    ("admin:teachers:attendance", "Manage teacher attendance"),
    ("admin:teachers:attendance:read", "View teacher attendance"),
    ("teacher:attendance:self_declare", "Teacher self-declare absence"),
]


_ROLE_PERMISSION_MATRIX = {
    "admin": [
        "admin:teachers:attendance",
        "admin:teachers:attendance:read",
        "teacher:attendance:self_declare",
    ],
    "director": [
        "admin:teachers:attendance",
        "admin:teachers:attendance:read",
        "teacher:attendance:self_declare",
    ],
    "staff": [
        "admin:teachers:attendance",
        "admin:teachers:attendance:read",
    ],
    "teacher": [
        "teacher:attendance:self_declare",
    ],
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
