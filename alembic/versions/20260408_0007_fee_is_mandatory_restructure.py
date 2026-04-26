"""Add is_mandatory to fee_categories, fee_category_id to optional_fee_options,
drop class_id from fee_variants, make level_id NOT NULL.

Revision ID: 0007
Revises: 0006
Create Date: 2026-04-08
"""

import sqlalchemy as sa

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add is_mandatory to fee_categories (default TRUE for existing rows)
    op.add_column(
        "fee_categories",
        sa.Column("is_mandatory", sa.Boolean(), nullable=False, server_default=sa.text("1")),
    )

    # 2. Add fee_category_id to optional_fee_options (nullable first for backfill)
    op.add_column(
        "optional_fee_options",
        sa.Column("fee_category_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_optional_fee_options_category",
        "optional_fee_options",
        "fee_categories",
        ["fee_category_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_optional_fee_options_fee_category_id",
        "optional_fee_options",
        ["fee_category_id"],
    )

    # 3. Drop class_id from fee_variants — FK was auto-named by MySQL (initial_schema
    # didn't pin a constraint name). Look it up in information_schema then drop it.
    bind = op.get_bind()
    fk_name = bind.execute(
        sa.text(
            """
            SELECT CONSTRAINT_NAME
            FROM information_schema.KEY_COLUMN_USAGE
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'fee_variants'
              AND COLUMN_NAME = 'class_id'
              AND REFERENCED_TABLE_NAME IS NOT NULL
            LIMIT 1
            """
        )
    ).scalar()
    if fk_name:
        op.drop_constraint(fk_name, "fee_variants", type_="foreignkey")
    op.drop_index("class_id", "fee_variants")
    op.drop_column("fee_variants", "class_id")

    # 4. Make level_id NOT NULL on fee_variants (backfill NULLs first)
    op.execute("UPDATE fee_variants SET level_id = 1 WHERE level_id IS NULL")
    op.alter_column("fee_variants", "level_id", existing_type=sa.BigInteger(), nullable=False)

    # 5. Add unique constraint on fee_variants
    op.create_unique_constraint(
        "uq_fee_variant_category_level_series_year",
        "fee_variants",
        ["fee_category_id", "level_id", "series_id", "academic_year_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_fee_variant_category_level_series_year", "fee_variants", type_="unique")
    op.alter_column("fee_variants", "level_id", existing_type=sa.BigInteger(), nullable=True)
    op.add_column("fee_variants", sa.Column("class_id", sa.BigInteger(), nullable=True))
    op.create_index("class_id", "fee_variants", ["class_id"])
    op.drop_index("ix_optional_fee_options_fee_category_id", "optional_fee_options")
    op.drop_constraint(
        "fk_optional_fee_options_category", "optional_fee_options", type_="foreignkey"
    )
    op.drop_column("optional_fee_options", "fee_category_id")
    op.drop_column("fee_categories", "is_mandatory")
