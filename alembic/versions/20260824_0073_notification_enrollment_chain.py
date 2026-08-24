"""Les deux temps de la chaîne d'inscription, comme types de notification.

Ouvrir un dossier, encaisser, valider : trois gestes que trois personnes
peuvent poser. Deux types distincts plutôt qu'un seul, parce qu'ils ne
s'adressent pas aux mêmes personnes et n'appellent pas la même action.

Revision ID: 0073_notification_enrollment_chain
Revises: 0072_notification_action_url
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0073_notification_enrollment_chain"
down_revision: str | None = "0072_notification_action_url"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ANCIENS = (
    "payment_due",
    "payment_received",
    "grade_available",
    "bulletin_published",
    "absence_recorded",
    "enrollment_status",
    "system",
)
_NOUVEAUX = (*_ANCIENS, "enrollment_awaiting_payment", "enrollment_awaiting_validation")


def _modifier(valeurs: Sequence[str]) -> None:
    liste = ", ".join(f"'{v}'" for v in valeurs)
    op.execute(
        sa.text(f"ALTER TABLE notifications MODIFY COLUMN type ENUM({liste}) NOT NULL")
    )


def upgrade() -> None:
    _modifier(_NOUVEAUX)


def downgrade() -> None:
    # Les notifications des deux nouveaux types redeviennent des changements
    # de statut d'inscription : les supprimer ferait disparaitre une tache que
    # quelqu'un attend peut-etre encore.
    op.execute(
        sa.text(
            "UPDATE notifications SET type = 'enrollment_status' "
            "WHERE type IN ('enrollment_awaiting_payment', 'enrollment_awaiting_validation')"
        )
    )
    _modifier(_ANCIENS)
