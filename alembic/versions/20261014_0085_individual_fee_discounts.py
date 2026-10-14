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
    # Seule la migration à vide est réversible sans altérer la comptabilité.
    # Une remise active doit d'abord être annulée via l'API et auditée.
    from sqlalchemy import text

    count = op.get_bind().execute(
        text("SELECT COUNT(*) FROM enrollment_fee_discounts")
    ).scalar_one()
    if count:
        raise RuntimeError(
            "Downgrade 0085 refusé : annulez les réductions actives par l'API "
            "avant de revenir en arrière."
        )
    op.drop_index("ix_enrollment_fee_discounts_enrollment_fee_id", table_name="enrollment_fee_discounts")
    op.drop_index("uq_enrollment_fee_discount", table_name="enrollment_fee_discounts")
    op.drop_table("enrollment_fee_discounts")
    op.execute(
        """
        DELETE rp FROM role_permissions rp
        JOIN permissions p ON p.id = rp.permission_id
        WHERE p.slug IN ('discounts:read', 'discounts:manage')
        """
    )
    op.execute(
        "DELETE FROM permissions WHERE slug IN ('discounts:read', 'discounts:manage')"
    )
