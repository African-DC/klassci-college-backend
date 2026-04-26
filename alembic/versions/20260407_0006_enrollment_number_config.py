"""add enrollment_number_pattern and counter to school_settings.

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-07
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers
revision: str = "0006"
down_revision: str = "0005"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "school_settings",
        sa.Column("enrollment_number_pattern", sa.String(200), nullable=True),
    )
    op.add_column(
        "school_settings",
        sa.Column(
            "enrollment_number_counter",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("school_settings", "enrollment_number_counter")
    op.drop_column("school_settings", "enrollment_number_pattern")
