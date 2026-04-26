"""Add city and commune to students and parents.

Revision ID: 0017
Revises: 0016
Create Date: 2026-04-15
"""
import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("students", sa.Column("city", sa.String(100), nullable=True))
    op.add_column("students", sa.Column("commune", sa.String(100), nullable=True))
    op.add_column("parents", sa.Column("city", sa.String(100), nullable=True))
    op.add_column("parents", sa.Column("commune", sa.String(100), nullable=True))


def downgrade() -> None:
    op.drop_column("parents", "commune")
    op.drop_column("parents", "city")
    op.drop_column("students", "commune")
    op.drop_column("students", "city")
