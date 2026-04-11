"""Add cancelled to payment status enum."""
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE payments MODIFY COLUMN status "
        "ENUM('pending','completed','failed','refunded','cancelled') "
        "NOT NULL DEFAULT 'pending'"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE payments MODIFY COLUMN status "
        "ENUM('pending','completed','failed','refunded') "
        "NOT NULL DEFAULT 'pending'"
    )
