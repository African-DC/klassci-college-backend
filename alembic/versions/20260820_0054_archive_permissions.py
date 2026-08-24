"""Droits de corbeille.

Archiver reste ouvert a qui pouvait deja supprimer : c'est reversible, et
exiger un droit de plus pour un geste rattrapable ajouterait de la friction
sans rien proteger.

Vider la corbeille est une autre affaire — c'est le seul geste du logiciel
qui ne se rattrape pas — et revient a la direction.

Revision ID: 0054_archive_permissions
Revises: 0053_recycle_bin
Create Date: 2026-08-20
"""

from alembic import op

revision = "0054_archive_permissions"
down_revision = "0053_recycle_bin"
branch_labels = None
depends_on = None

_PERMISSIONS = (
    ("archive:read", "Browse the recycle bin"),
    ("archive:purge", "Permanently delete an archived record"),
)
_ROLES = ("admin", "director")


def upgrade() -> None:
    values = ", ".join(f"('{slug}', '{name}')" for slug, name in _PERMISSIONS)
    op.execute(f"INSERT IGNORE INTO permissions (slug, name) VALUES {values}")

    slugs = ", ".join(f"'{slug}'" for slug, _ in _PERMISSIONS)
    for role in _ROLES:
        op.execute(
            f"""
            INSERT IGNORE INTO role_permissions (role_id, permission_id)
            SELECT r.id, p.id FROM roles r CROSS JOIN permissions p
            WHERE r.name = '{role}' AND p.slug IN ({slugs})
            """
        )


def downgrade() -> None:
    slugs = ", ".join(f"'{slug}'" for slug, _ in _PERMISSIONS)
    op.execute(
        f"""
        DELETE rp FROM role_permissions rp
        JOIN permissions p ON p.id = rp.permission_id
        WHERE p.slug IN ({slugs})
        """
    )
    op.execute(f"DELETE FROM permissions WHERE slug IN ({slugs})")
