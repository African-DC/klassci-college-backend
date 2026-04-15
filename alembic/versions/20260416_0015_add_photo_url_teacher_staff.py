"""Add photo_url to teacher_profiles and staff_profiles.

Revision ID: 0015
Revises: 0014
Create Date: 2026-04-15
"""

from alembic import op
import sqlalchemy as sa

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("teacher_profiles", sa.Column("photo_url", sa.String(500), nullable=True))
    op.add_column("staff_profiles", sa.Column("photo_url", sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column("staff_profiles", "photo_url")
    op.drop_column("teacher_profiles", "photo_url")
