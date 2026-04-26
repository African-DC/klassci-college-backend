"""Add timetable generation settings to school_settings.

Revision ID: 0014
Revises: 0013
Create Date: 2026-04-13
"""

from alembic import op
import sqlalchemy as sa

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "school_settings",
        sa.Column("slot_duration_minutes", sa.Integer(), nullable=False, server_default="60"),
    )
    op.add_column(
        "school_settings",
        sa.Column("day_start_hour", sa.Integer(), nullable=False, server_default="7"),
    )
    op.add_column(
        "school_settings",
        sa.Column("day_end_hour", sa.Integer(), nullable=False, server_default="17"),
    )


def downgrade() -> None:
    op.drop_column("school_settings", "day_end_hour")
    op.drop_column("school_settings", "day_start_hour")
    op.drop_column("school_settings", "slot_duration_minutes")
