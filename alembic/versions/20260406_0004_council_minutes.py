"""Add council_minutes and council_student_decisions tables.

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-06
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "council_minutes",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("class_id", sa.BigInteger(), nullable=False),
        sa.Column("academic_year_id", sa.BigInteger(), nullable=False),
        sa.Column("trimester", sa.Integer(), nullable=False),
        sa.Column("main_teacher_name", sa.String(200), nullable=True),
        sa.Column("director_name", sa.String(200), nullable=True),
        sa.Column("dren_name", sa.String(200), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("generated_at", sa.DateTime(), nullable=True),
        sa.Column("is_published", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["class_id"], ["classes.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["academic_year_id"], ["academic_years.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("class_id", "academic_year_id", "trimester", name="uq_council_class_year_trim"),
    )
    op.create_index("idx_council_minutes_class_id", "council_minutes", ["class_id"])
    op.create_index("idx_council_minutes_academic_year_id", "council_minutes", ["academic_year_id"])

    op.create_table(
        "council_student_decisions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("council_minutes_id", sa.BigInteger(), nullable=False),
        sa.Column("student_id", sa.BigInteger(), nullable=False),
        sa.Column("average", sa.Numeric(4, 2), nullable=True),
        sa.Column("rank", sa.Integer(), nullable=True),
        sa.Column("absence_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("auto_decision", sa.String(50), nullable=False),
        sa.Column("final_decision", sa.String(50), nullable=True),
        sa.Column("override_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["council_minutes_id"], ["council_minutes.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_council_decisions_council_id", "council_student_decisions", ["council_minutes_id"]
    )
    op.create_index(
        "idx_council_decisions_student_id", "council_student_decisions", ["student_id"]
    )


def downgrade() -> None:
    op.drop_table("council_student_decisions")
    op.drop_table("council_minutes")
