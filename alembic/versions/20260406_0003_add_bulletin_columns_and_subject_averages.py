"""Add bulletin columns (teacher_comment, council_decision) and subject_averages table.

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-06
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # --- Add columns to bulletins ---
    op.add_column("bulletins", sa.Column("teacher_comment", sa.Text(), nullable=True))
    op.add_column(
        "bulletins",
        sa.Column(
            "council_decision",
            sa.Enum("passage", "repechage", "redoublement", "exclusion", name="council_decision"),
            nullable=True,
        ),
    )

    # --- Create subject_averages table ---
    op.create_table(
        "subject_averages",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("bulletin_id", sa.BigInteger(), nullable=False),
        sa.Column("subject_id", sa.BigInteger(), nullable=False),
        sa.Column("student_id", sa.BigInteger(), nullable=False),
        sa.Column("trimester", sa.Integer(), nullable=False),
        sa.Column("average", sa.Numeric(4, 2), nullable=False),
        sa.Column("coefficient", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["bulletin_id"], ["bulletins.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["subject_id"], ["subjects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"], ondelete="RESTRICT"),
    )
    op.create_index("idx_subject_averages_bulletin_id", "subject_averages", ["bulletin_id"])
    op.create_index("idx_subject_averages_subject_id", "subject_averages", ["subject_id"])
    op.create_index("idx_subject_averages_student_id", "subject_averages", ["student_id"])


def downgrade() -> None:
    op.drop_table("subject_averages")
    op.drop_column("bulletins", "council_decision")
    op.drop_column("bulletins", "teacher_comment")
    op.execute("DROP TYPE IF EXISTS council_decision")
