"""Foundation Documents Admin : SchoolSettings columns for official PDFs + documents:* perms.

PR #3 du Plan B-revised. Prepare le terrain pour le Certificat de scolarite
(PR #4) en ajoutant les colonnes signature/head_master sur SchoolSettings et
en seedant les permissions documents:certificate et documents:attendance.

Sans cette migration, les endpoints PR #4 retourneraient 403 silent en prod
chez les tenants existants (cf. memory feedback_permission_seed_audit).

Revision ID: 0023
Revises: 0022
Create Date: 2026-04-28
"""

import sqlalchemy as sa

from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


_NEW_PERMISSIONS = [
    ("documents:certificate", "Generate certificat de scolarite"),
    ("documents:attendance", "Generate attestation de frequentation"),
]


def upgrade() -> None:
    # 1. Add nullable columns on school_settings
    op.add_column(
        "school_settings",
        sa.Column("signature_image_url", sa.String(500), nullable=True),
    )
    op.add_column(
        "school_settings",
        sa.Column("head_master_name", sa.String(200), nullable=True),
    )
    op.add_column(
        "school_settings",
        sa.Column("head_master_title", sa.String(100), nullable=True),
    )

    # 2. Seed permissions
    for slug, name in _NEW_PERMISSIONS:
        op.execute(
            f"INSERT IGNORE INTO permissions (slug, name) VALUES ('{slug}', '{name}')"
        )
        op.execute(
            f"""
            INSERT IGNORE INTO role_permissions (role_id, permission_id)
            SELECT r.id, p.id
            FROM roles r
            CROSS JOIN permissions p
            WHERE r.name IN ('admin', 'director')
            AND p.slug = '{slug}'
            """
        )


def downgrade() -> None:
    # 1. Remove role_permissions + permissions
    for slug, _ in _NEW_PERMISSIONS:
        op.execute(
            f"""
            DELETE rp FROM role_permissions rp
            JOIN permissions p ON rp.permission_id = p.id
            WHERE p.slug = '{slug}'
            """
        )
        op.execute(f"DELETE FROM permissions WHERE slug = '{slug}'")

    # 2. Drop columns (reverse order)
    op.drop_column("school_settings", "head_master_title")
    op.drop_column("school_settings", "head_master_name")
    op.drop_column("school_settings", "signature_image_url")
