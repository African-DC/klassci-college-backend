"""Cloisonne la lecture des montants dus par une famille.

Ce qu'une famille doit dit sa situation economique. Jusqu'ici, toute personne
pouvant ouvrir une fiche eleve voyait « Reste a payer », y compris le
directeur des etudes qui n'a aucun droit financier et qui preside les
conseils de classe.

Deux niveaux desormais :

- `payments:read` — les montants, pour qui manipule l'argent.
- `payments:status:read` — « a jour » ou « en retard » et la date du dernier
  versement, sans aucune somme. De quoi valider un dossier d'inscription.

La revocation porte sur les etablissements deja ouverts : sans elle, la
correction ne change rien la ou elle compte. Tout reste recochable depuis
l'ecran Roles et permissions, qui edite deja `role_permissions`.

Revision ID: 0049_finance_visibility
Revises: 0048_audit_journal
Create Date: 2026-08-20
"""

from alembic import op

revision = "0049_finance_visibility"
down_revision = "0048_audit_journal"
branch_labels = None
depends_on = None

_STATUS_SLUG = "payments:status:read"

# Qui gagne l'etat de paiement sans les montants.
_GRANT_STATUS = ("admin", "director", "educator", "studies_director")

# Qui perd quoi. L'educateur perd les montants ; le secretariat garde sa
# caisse mais perd la vue sur celles des autres, qui revient au comptable.
_REVOKE = {
    "educator": ("payments:read",),
    "staff": ("payments:read:all", "cash-session:read:all"),
}


def upgrade() -> None:
    op.execute(
        f"INSERT IGNORE INTO permissions (slug, name) "
        f"VALUES ('{_STATUS_SLUG}', 'See payment status without amounts')"
    )

    for role_name in _GRANT_STATUS:
        op.execute(
            f"""
            INSERT IGNORE INTO role_permissions (role_id, permission_id)
            SELECT r.id, p.id
            FROM roles r
            CROSS JOIN permissions p
            WHERE r.name = '{role_name}' AND p.slug = '{_STATUS_SLUG}'
            """
        )

    for role_name, slugs in _REVOKE.items():
        slugs_sql = ", ".join(f"'{slug}'" for slug in slugs)
        op.execute(
            f"""
            DELETE rp FROM role_permissions rp
            JOIN roles r ON r.id = rp.role_id
            JOIN permissions p ON p.id = rp.permission_id
            WHERE r.name = '{role_name}' AND p.slug IN ({slugs_sql})
            """
        )


def downgrade() -> None:
    # On rend au secretariat et a l'educateur ce qu'ils avaient, puis on
    # retire la permission d'etat qui n'existait pas avant.
    for role_name, slugs in _REVOKE.items():
        slugs_sql = ", ".join(f"'{slug}'" for slug in slugs)
        op.execute(
            f"""
            INSERT IGNORE INTO role_permissions (role_id, permission_id)
            SELECT r.id, p.id
            FROM roles r
            CROSS JOIN permissions p
            WHERE r.name = '{role_name}' AND p.slug IN ({slugs_sql})
            """
        )

    op.execute(
        f"""
        DELETE rp FROM role_permissions rp
        JOIN permissions p ON p.id = rp.permission_id
        WHERE p.slug = '{_STATUS_SLUG}'
        """
    )
    op.execute(f"DELETE FROM permissions WHERE slug = '{_STATUS_SLUG}'")
