"""Fournitures en nature : un article déposé n'est plus dû en argent.

Ajoute `fee_categories.accepts_in_kind` (le comptable coche « Ramette »),
étend `enrollment_fee_status` de `in_kind`, et trace le dépôt sur la ligne
(`deposited_at`, `deposited_by_user_id`).

`in_kind` n'est PAS `waived` : une exonération gonfle les chiffres DRENA,
un dépôt de ramette non.

Revision ID: 0076_in_kind_deposits
Revises: 0075_student_search_key
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0076_in_kind_deposits"
down_revision: str | None = "0075_student_search_key"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATUS_WITH = "ENUM('pending','partial','paid','waived','in_kind')"
_STATUS_WITHOUT = "ENUM('pending','partial','paid','waived')"


def upgrade() -> None:
    op.add_column(
        "fee_categories",
        sa.Column("accepts_in_kind", sa.Boolean(), nullable=False, server_default=sa.text("0")),
    )
    op.execute(
        "ALTER TABLE enrollment_fees MODIFY COLUMN status "
        f"{_STATUS_WITH} NOT NULL DEFAULT 'pending'"
    )
    op.add_column("enrollment_fees", sa.Column("deposited_at", sa.DateTime(), nullable=True))
    op.add_column(
        "enrollment_fees",
        sa.Column("deposited_by_user_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_enrollment_fees_deposited_by_user_id",
        "enrollment_fees",
        "users",
        ["deposited_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.execute(
        "UPDATE enrollment_fees SET status = 'pending' "
        "WHERE status = 'in_kind'"
    )
    op.drop_constraint(
        "fk_enrollment_fees_deposited_by_user_id", "enrollment_fees", type_="foreignkey"
    )
    op.drop_column("enrollment_fees", "deposited_by_user_id")
    op.drop_column("enrollment_fees", "deposited_at")
    op.execute(
        "ALTER TABLE enrollment_fees MODIFY COLUMN status "
        f"{_STATUS_WITHOUT} NOT NULL DEFAULT 'pending'"
    )
    op.drop_column("fee_categories", "accepts_in_kind")
