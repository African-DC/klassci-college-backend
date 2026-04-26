"""add level_id and series_id to fee_variants.

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-07
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers
revision: str = "0005"
down_revision: str = "0004"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("fee_variants", sa.Column("level_id", sa.BigInteger(), nullable=True))
    op.add_column("fee_variants", sa.Column("series_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        "fk_fee_variants_level",
        "fee_variants",
        "levels",
        ["level_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_fee_variants_series",
        "fee_variants",
        "series",
        ["series_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("idx_fee_variants_level_id", "fee_variants", ["level_id"])
    op.create_index("idx_fee_variants_series_id", "fee_variants", ["series_id"])


def downgrade() -> None:
    op.drop_constraint("fk_fee_variants_series", "fee_variants", type_="foreignkey")
    op.drop_constraint("fk_fee_variants_level", "fee_variants", type_="foreignkey")
    op.drop_index("idx_fee_variants_series_id", "fee_variants")
    op.drop_index("idx_fee_variants_level_id", "fee_variants")
    op.drop_column("fee_variants", "series_id")
    op.drop_column("fee_variants", "level_id")
