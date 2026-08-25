"""Intérim : colonne interim_teacher_id sur leave_requests (remplaçant).

Revision ID: 0038_leave_interim
Revises: 0037_leave_requests
Create Date: 2026-07-03
"""

import sqlalchemy as sa

from alembic import op

revision = "0038_leave_interim"
down_revision = "0037_leave_requests"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "leave_requests",
        sa.Column("interim_teacher_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_leave_requests_interim_teacher",
        "leave_requests",
        "teacher_profiles",
        ["interim_teacher_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_leave_requests_interim_teacher", "leave_requests", type_="foreignkey")
    op.drop_column("leave_requests", "interim_teacher_id")
