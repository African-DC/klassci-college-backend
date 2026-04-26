"""Seed student and parent roles.

Revision ID: 0016
Revises: 0015
Create Date: 2026-04-15
"""
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Insert student and parent roles
    op.execute("INSERT IGNORE INTO roles (name) VALUES ('student'), ('parent')")

    # Assign student role to existing users with student profiles
    op.execute("""
        INSERT IGNORE INTO user_roles (user_id, role_id)
        SELECT s.user_id, r.id FROM students s
        JOIN roles r ON r.name = 'student'
        WHERE s.user_id IS NOT NULL
    """)

    # Assign teacher role to existing users with teacher profiles (if missing)
    op.execute("""
        INSERT IGNORE INTO user_roles (user_id, role_id)
        SELECT t.user_id, r.id FROM teacher_profiles t
        JOIN roles r ON r.name = 'teacher'
        WHERE t.user_id IS NOT NULL
        AND NOT EXISTS (
            SELECT 1 FROM user_roles ur
            WHERE ur.user_id = t.user_id AND ur.role_id = r.id
        )
    """)

    # Add parent CRUD permissions
    op.execute("""
        INSERT IGNORE INTO permissions (slug, name) VALUES
        ('admin:parents:read', 'View parents'),
        ('admin:parents:create', 'Create parents'),
        ('admin:parents:update', 'Update parents'),
        ('admin:parents:delete', 'Delete parents')
    """)

    # Grant parent permissions to admin and director roles
    op.execute("""
        INSERT IGNORE INTO role_permissions (role_id, permission_id)
        SELECT r.id, p.id
        FROM roles r
        CROSS JOIN permissions p
        WHERE r.name IN ('admin', 'director')
        AND p.slug IN (
            'admin:parents:read',
            'admin:parents:create',
            'admin:parents:update',
            'admin:parents:delete'
        )
    """)


def downgrade() -> None:
    # Remove parent permissions from roles
    op.execute("""
        DELETE rp FROM role_permissions rp
        JOIN permissions p ON rp.permission_id = p.id
        WHERE p.slug IN (
            'admin:parents:read',
            'admin:parents:create',
            'admin:parents:update',
            'admin:parents:delete'
        )
    """)

    # Remove parent permissions
    op.execute("""
        DELETE FROM permissions WHERE slug IN (
            'admin:parents:read',
            'admin:parents:create',
            'admin:parents:update',
            'admin:parents:delete'
        )
    """)

    # Remove student/parent role assignments
    op.execute("""
        DELETE ur FROM user_roles ur
        JOIN roles r ON ur.role_id = r.id
        WHERE r.name IN ('student', 'parent')
    """)

    # Remove roles
    op.execute("DELETE FROM roles WHERE name IN ('student', 'parent')")
