"""Add preferred column to teacher_availabilities.

Revision ID: 0013
Revises: 0012
Create Date: 2026-04-13
"""

from alembic import op
import sqlalchemy as sa

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "teacher_availabilities",
        sa.Column("preferred", sa.Boolean(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("teacher_availabilities", "preferred")
