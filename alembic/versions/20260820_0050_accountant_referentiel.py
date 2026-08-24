"""Donne au comptable la configuration complete de la grille tarifaire.

La grille se decline par niveau et par serie. Un comptable qui peut creer une
categorie de frais mais pas le niveau auquel l'appliquer reste bloque au
milieu de sa configuration et doit reclamer un administrateur.

Revision ID: 0050_accountant_referentiel
Revises: 0049_finance_visibility
Create Date: 2026-08-20
"""

from alembic import op

revision = "0050_accountant_referentiel"
down_revision = "0049_finance_visibility"
branch_labels = None
depends_on = None

_SLUGS = (
    "admin:levels:create",
    "admin:levels:update",
    "admin:levels:delete",
    "admin:series:write",
)


def upgrade() -> None:
    slugs_sql = ", ".join(f"'{slug}'" for slug in _SLUGS)
    op.execute(
        f"""
        INSERT IGNORE INTO role_permissions (role_id, permission_id)
        SELECT r.id, p.id
        FROM roles r
        CROSS JOIN permissions p
        WHERE r.name = 'accountant' AND p.slug IN ({slugs_sql})
        """
    )


def downgrade() -> None:
    slugs_sql = ", ".join(f"'{slug}'" for slug in _SLUGS)
    op.execute(
        f"""
        DELETE rp FROM role_permissions rp
        JOIN roles r ON r.id = rp.role_id
        JOIN permissions p ON p.id = rp.permission_id
        WHERE r.name = 'accountant' AND p.slug IN ({slugs_sql})
        """
    )
