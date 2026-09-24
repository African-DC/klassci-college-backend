"""Versements : une clé par envoi, pour qu'un renvoi n'encaisse pas deux fois.

Au guichet, sur une 3G qui coupe, la caissière appuie sur « Enregistrer »,
l'écran tourne, elle appuie encore. Le premier envoi était peut-être déjà
passé : le serveur enregistrait alors un second versement du même montant,
et le tiroir comptait un billet qui n'existe pas.

L'écran tire désormais une clé au moment de l'envoi et la renvoie telle
quelle à chaque nouvelle tentative. La contrainte d'unicité fait le reste :
une clé déjà vue rend le versement déjà écrit au lieu d'en écrire un autre.

La colonne accepte `NULL` : les versements déjà en base n'ont pas de clé, et
les clients qui n'en envoient pas encore gardent le comportement d'avant.
MySQL admet plusieurs `NULL` sous un index unique.

Revision ID: 0083_payment_idempotency_key
Revises: 0082_audit_subject_label
Create Date: 2026-09-24
"""

import sqlalchemy as sa

from alembic import op

revision = "0083_payment_idempotency_key"
down_revision = "0082_audit_subject_label"
branch_labels = None
depends_on = None

_INDEX = "uq_payments_idempotency_key"


def _has_column() -> bool:
    return bool(
        op.get_bind()
        .execute(
            sa.text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_schema = DATABASE() AND table_name = 'payments' "
                "AND column_name = 'idempotency_key'"
            )
        )
        .scalar()
    )


def _has_index() -> bool:
    return bool(
        op.get_bind()
        .execute(
            sa.text(
                "SELECT 1 FROM information_schema.statistics "
                "WHERE table_schema = DATABASE() AND table_name = 'payments' "
                "AND index_name = :name"
            ),
            {"name": _INDEX},
        )
        .scalar()
    )


def upgrade() -> None:
    if not _has_column():
        op.add_column("payments", sa.Column("idempotency_key", sa.String(64), nullable=True))
    if not _has_index():
        op.create_index(_INDEX, "payments", ["idempotency_key"], unique=True)


def downgrade() -> None:
    if _has_index():
        op.drop_index(_INDEX, table_name="payments")
    if _has_column():
        op.drop_column("payments", "idempotency_key")
