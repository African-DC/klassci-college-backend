"""teacher_session_attendance — pointage enseignant par créneau EDT

Phase 7b (KLASSCI College 2026-05-19) — Marcel a tranché :
- Granularité : par slot EDT (slot_id nullable pour absences hors EDT)
- Saisie hybride : admin/staff (validé direct) OU prof self-déclaré (validation après)
- Retards : compteur minutes (int précis pour calcul salaire DREN)

Revision ID: 0030_teacher_attendance
Revises: 0029_school_pdf_customization
Create Date: 2026-05-19
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0030_teacher_attendance"
down_revision = "0029_school_pdf_customization"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "teacher_session_attendance",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("teacher_id", sa.BigInteger(), nullable=False),
        sa.Column("slot_id", sa.BigInteger(), nullable=True),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("academic_year_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "present",
                "absent_excused",
                "absent_unexcused",
                "late",
                name="teacher_attendance_status",
            ),
            nullable=False,
            server_default="present",
        ),
        sa.Column("late_minutes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("declared_by_user_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "declared_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "is_validated",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column("validated_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("validated_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["teacher_id"], ["teacher_profiles.id"], ondelete="RESTRICT",
            name="fk_tsa_teacher",
        ),
        sa.ForeignKeyConstraint(
            ["slot_id"], ["timetable_slots.id"], ondelete="SET NULL",
            name="fk_tsa_slot",
        ),
        sa.ForeignKeyConstraint(
            ["academic_year_id"], ["academic_years.id"], ondelete="RESTRICT",
            name="fk_tsa_academic_year",
        ),
        sa.ForeignKeyConstraint(
            ["declared_by_user_id"], ["users.id"], ondelete="RESTRICT",
            name="fk_tsa_declared_by",
        ),
        sa.ForeignKeyConstraint(
            ["validated_by_user_id"], ["users.id"], ondelete="SET NULL",
            name="fk_tsa_validated_by",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_tsa_teacher_date",
        "teacher_session_attendance",
        ["teacher_id", "date"],
    )
    op.create_index(
        "idx_tsa_slot",
        "teacher_session_attendance",
        ["slot_id"],
    )
    op.create_index(
        "idx_tsa_ay_status",
        "teacher_session_attendance",
        ["academic_year_id", "status"],
    )
    op.create_index(
        "idx_tsa_validation",
        "teacher_session_attendance",
        ["is_validated"],
    )


def downgrade() -> None:
    # Drop FKs before indexes (MySQL 1553 prevention — voir migration 0028)
    op.drop_constraint("fk_tsa_validated_by", "teacher_session_attendance", type_="foreignkey")
    op.drop_constraint("fk_tsa_declared_by", "teacher_session_attendance", type_="foreignkey")
    op.drop_constraint("fk_tsa_academic_year", "teacher_session_attendance", type_="foreignkey")
    op.drop_constraint("fk_tsa_slot", "teacher_session_attendance", type_="foreignkey")
    op.drop_constraint("fk_tsa_teacher", "teacher_session_attendance", type_="foreignkey")
    op.drop_index("idx_tsa_validation", table_name="teacher_session_attendance")
    op.drop_index("idx_tsa_ay_status", table_name="teacher_session_attendance")
    op.drop_index("idx_tsa_slot", table_name="teacher_session_attendance")
    op.drop_index("idx_tsa_teacher_date", table_name="teacher_session_attendance")
    op.drop_table("teacher_session_attendance")
