"""Trace de l'annulation d'un versement : quand, par qui, et pourquoi.

Le statut `cancelled` existait deja, et la contre-passation aussi : les
allocations sont defaites, les statuts de frais recalcules, l'audit ecrit.
Mais la ligne annulee ne portait rien. Or l'annulation d'un encaissement est
exactement l'ecriture qu'un controle vient relire : sans motif ni signataire
sur la ligne elle-meme, elle ne se defend pas.

Le principe d'intangibilite (SYSCOHADA) veut qu'on ne supprime pas une
ecriture mais qu'on la contre-passe, en laissant une trace au moins aussi
visible que l'encaissement. Ces trois colonnes sont cette trace.

Revision ID: 0071_cancel_reason
Revises: 0070_availability_self
Create Date: 2026-08-23
"""

import sqlalchemy as sa

from alembic import op

revision = "0071_cancel_reason"
down_revision = "0070_availability_self"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("payments", sa.Column("cancelled_at", sa.DateTime(), nullable=True))
    op.add_column("payments", sa.Column("cancelled_by", sa.BigInteger(), nullable=True))
    op.add_column("payments", sa.Column("cancellation_reason", sa.String(500), nullable=True))
    op.create_foreign_key(
        "fk_payments_cancelled_by",
        "payments",
        "users",
        ["cancelled_by"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_payments_cancelled_by", "payments", type_="foreignkey")
    op.drop_column("payments", "cancellation_reason")
    op.drop_column("payments", "cancelled_by")
    op.drop_column("payments", "cancelled_at")
