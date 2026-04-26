"""Add photo_url to students table."""
from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("students", sa.Column("photo_url", sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column("students", "photo_url")
