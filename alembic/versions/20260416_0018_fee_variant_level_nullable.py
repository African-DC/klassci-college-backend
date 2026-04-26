"""Make fee_variants.level_id nullable for global optional fees.

Optional fees like CANTINE are a flat price regardless of level.
They should have level_id=NULL to apply to all levels.

Revision ID: 0018
Revises: 0017
Create Date: 2026-04-15
"""

from alembic import op
import sqlalchemy as sa

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "fee_variants",
        "level_id",
        existing_type=sa.BigInteger(),
        nullable=True,
    )


def downgrade() -> None:
    # Set NULL level_ids to a default before making NOT NULL again
    op.execute("UPDATE fee_variants SET level_id = 1 WHERE level_id IS NULL")
    op.alter_column(
        "fee_variants",
        "level_id",
        existing_type=sa.BigInteger(),
        nullable=False,
    )
