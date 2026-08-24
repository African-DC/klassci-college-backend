"""Gestion des comptes des acteurs.

- Ajoute `users.must_change_password` (changement forcé du mot de passe temporaire
  à la 1re connexion, après création/réinitialisation par un admin).
- Seed la permission `admin:accounts:manage`, accordée à `admin`, `director`,
  `staff` (le secrétariat gère les comptes élèves/parents).

Revision ID: 0040_account_management
Revises: 0039_mailpulse_config
Create Date: 2026-07-04
"""

import sqlalchemy as sa

from alembic import op

revision = "0040_account_management"
down_revision = "0039_mailpulse_config"
branch_labels = None
depends_on = None


_NEW_PERMISSIONS = [
    ("admin:accounts:manage", "Manage actor login accounts"),
]

_ROLE_PERMISSION_MATRIX = {
    "admin": ["admin:accounts:manage"],
    "director": ["admin:accounts:manage"],
    "staff": ["admin:accounts:manage"],
}


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "must_change_password",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )

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
    op.drop_column("users", "must_change_password")
