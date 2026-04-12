"""Add color field to subjects table.

Revision ID: 0011
Revises: 0010
Create Date: 2026-04-16
"""

from alembic import op
import sqlalchemy as sa

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("subjects", sa.Column("color", sa.String(20), nullable=True))


def downgrade() -> None:
    op.drop_column("subjects", "color")
