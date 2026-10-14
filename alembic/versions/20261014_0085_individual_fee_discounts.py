"""Réductions individuelles et permissions, par base établissement.

La valeur nominale reste dans original_amount ; enrollment_fees.amount porte
le net dû, afin que caisse, reçus, échéanciers et portails voient une seule dette.
La migration est additive et ne modifie aucun frais existant.

Revision ID: 0085_fee_discounts
Revises: 0084_information_sheet
Create Date: 2026-10-14
"""

from alembic import op
import sqlalchemy as sa

revision = "0085_fee_discounts"
down_revision = "0084_information_sheet"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "enrollment_fee_discounts",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("enrollment_fee_id", sa.BigInteger(), nullable=False),
        sa.Column("original_amount", sa.Numeric(15, 2), nullable=False),
        sa.Column("discount_amount", sa.Numeric(15, 2), nullable=False),
        sa.Column("kind", sa.String(12), nullable=False),
        sa.Column("value", sa.Numeric(15, 2), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("granted_by", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["enrollment_fee_id"], ["enrollment_fees.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["granted_by"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("uq_enrollment_fee_discount", "enrollment_fee_discounts", ["enrollment_fee_id"], unique=True)
    op.create_index("ix_enrollment_fee_discounts_enrollment_fee_id", "enrollment_fee_discounts", ["enrollment_fee_id"])
    op.execute(
        "INSERT IGNORE INTO permissions (slug, name) VALUES "
        "('discounts:read', 'View individual fee discounts'), "
        "('discounts:manage', 'Grant, change and cancel individual fee discounts')"
    )
    op.execute(
        """
        INSERT IGNORE INTO role_permissions (role_id, permission_id)
        SELECT r.id, p.id FROM roles r CROSS JOIN permissions p
        WHERE (r.name IN ('admin', 'director') AND p.slug IN ('discounts:read', 'discounts:manage'))
           OR (r.name = 'accountant' AND p.slug = 'discounts:read')
        """
    )


def downgrade() -> None:
    # Retirer une table de remises actives sans restaurer les dettes ferait
    # mentir les soldes. Le retour en arrière se prépare manuellement.
    raise RuntimeError(
        "Downgrade 0085 bloqué : réconcilier et annuler les réductions "
        "avant toute suppression de la table."
    )
