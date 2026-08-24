"""MailPulse : colonnes de config sur school_settings + permissions mailpulse:*.

Revision ID: 0039_mailpulse_config
Revises: 0038_leave_interim
Create Date: 2026-07-04
"""

import sqlalchemy as sa

from alembic import op

revision = "0039_mailpulse_config"
down_revision = "0038_leave_interim"
branch_labels = None
depends_on = None


_NEW_PERMISSIONS = [
    ("mailpulse:manage", "Configure MailPulse notifications"),
    ("mailpulse:test", "Send MailPulse test notifications"),
]

_ROLE_PERMISSION_MATRIX = {
    "admin": ["mailpulse:manage", "mailpulse:test"],
    "director": ["mailpulse:manage", "mailpulse:test"],
}

_COLUMNS = [
    ("mailpulse_enabled", sa.Boolean(), False, "0"),
    ("mailpulse_base_url", sa.String(255), True, None),
    ("mailpulse_api_key", sa.String(255), True, None),
    ("mailpulse_sender_email", sa.String(255), True, None),
    ("mailpulse_sender_name", sa.String(100), True, None),
    ("mailpulse_default_language", sa.String(5), False, "fr"),
    ("mailpulse_timeout", sa.Integer(), False, "20"),
    ("mailpulse_real_workflows_enabled", sa.Boolean(), False, "0"),
    ("mailpulse_test_email_enabled", sa.Boolean(), False, "1"),
    ("mailpulse_test_whatsapp_enabled", sa.Boolean(), False, "1"),
    ("mailpulse_test_email_recipients", sa.JSON(), True, None),
    ("mailpulse_test_phone_recipients", sa.JSON(), True, None),
    ("mailpulse_inbound_secret", sa.String(255), True, None),
]


def upgrade() -> None:
    for name, type_, nullable, server_default in _COLUMNS:
        op.add_column(
            "school_settings",
            sa.Column(name, type_, nullable=nullable, server_default=server_default),
        )

    values_sql = ", ".join(f"('{slug}', '{name}')" for slug, name in _NEW_PERMISSIONS)
    op.execute(f"INSERT IGNORE INTO permissions (slug, name) VALUES {values_sql}")
    for role_name, slugs in _ROLE_PERMISSION_MATRIX.items():
        slugs_sql = ", ".join(f"'{slug}'" for slug in slugs)
        op.execute(
            f"""
            INSERT IGNORE INTO role_permissions (role_id, permission_id)
            SELECT r.id, p.id FROM roles r CROSS JOIN permissions p
            WHERE r.name = '{role_name}' AND p.slug IN ({slugs_sql})
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
    for name, *_ in reversed(_COLUMNS):
        op.drop_column("school_settings", name)
