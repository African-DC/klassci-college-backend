"""Add room_type and timestamps to rooms table.

Revision ID: 0010
Revises: 0009
Create Date: 2026-04-16
"""

from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "rooms",
        sa.Column("room_type", sa.String(30), nullable=False, server_default="classroom"),
    )
    op.add_column(
        "rooms",
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.add_column(
        "rooms",
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("rooms", "updated_at")
    op.drop_column("rooms", "created_at")
    op.drop_column("rooms", "room_type")
