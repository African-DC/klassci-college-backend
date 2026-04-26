"""Add teacher_id to subjects table.

Revision ID: 0012
Revises: 0011
Create Date: 2026-04-16
"""

from alembic import op
import sqlalchemy as sa

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("subjects", sa.Column("teacher_id", sa.BigInteger(), nullable=True))
    op.create_index("idx_subjects_teacher_id", "subjects", ["teacher_id"])
    op.create_foreign_key(
        "fk_subjects_teacher_id",
        "subjects",
        "teacher_profiles",
        ["teacher_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_subjects_teacher_id", "subjects", type_="foreignkey")
    op.drop_index("idx_subjects_teacher_id", "subjects")
    op.drop_column("subjects", "teacher_id")
