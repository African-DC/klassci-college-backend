"""Valider une inscription devient un droit qu'on peut confier seul.

La validation etait gardee par `enrollments:update`. Pour laisser quelqu'un
valider, il fallait donc lui donner le droit de tout modifier — et la
permission n'apparaissait nulle part dans l'ecran des roles, puisqu'elle
n'existait pas. Impossible de confier la validation au directeur des etudes
sans lui ouvrir l'edition complete des dossiers.

Le droit est seme a tous les roles qui detiennent deja `enrollments:update` :
personne ne perd la capacite qu'il avait ce matin. Ce que la migration change,
c'est qu'on peut desormais la retirer, ou la donner seule.

Revision ID: 0074_enrol_validate_perm
Revises: 0073_notif_enrol_chain
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0074_enrol_validate_perm"
down_revision: str | None = "0073_notif_enrol_chain"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SLUG = "enrollments:validate"
_NOM = "Validate an enrollment"


def upgrade() -> None:
    op.execute(f"INSERT IGNORE INTO permissions (slug, name) VALUES ('{_SLUG}', '{_NOM}')")

    # Tout role qui pouvait valider hier peut valider aujourd'hui. Sans cette
    # reprise, changer la garde de l'endpoint retirerait silencieusement la
    # validation a ceux qui l'exercent — une ecole se retrouverait bloquee au
    # milieu de ses inscriptions sans qu'aucun message ne l'explique.
    op.execute(
        f"""
        INSERT IGNORE INTO role_permissions (role_id, permission_id)
        SELECT rp.role_id, p_new.id
        FROM role_permissions rp
        JOIN permissions p_old ON p_old.id = rp.permission_id
        CROSS JOIN permissions p_new
        WHERE p_old.slug = 'enrollments:update'
        AND p_new.slug = '{_SLUG}'
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        DELETE rp FROM role_permissions rp
        JOIN permissions p ON rp.permission_id = p.id
        WHERE p.slug = '{_SLUG}'
        """
    )
    op.execute(f"DELETE FROM permissions WHERE slug = '{_SLUG}'")
