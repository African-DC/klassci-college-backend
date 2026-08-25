"""document_issuances — registre d'émission pour la vérification publique

Phase 5 refonte PDF (KLASSCI College 2026-06-28) : chaque document officiel
généré (certificat, attestation, bulletin) est enregistré avec un jeton public
non devinable. Un QR code encodant l'URL de vérification est imprimé sur le PDF.

Revision ID: 0032_document_issuances
Revises: 0031_teacher_attendance_perms
Create Date: 2026-06-28
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0032_document_issuances"
down_revision = "0031_teacher_attendance_perms"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "document_issuances",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("token", sa.String(length=64), nullable=False),
        sa.Column("cev_code", sa.String(length=32), nullable=False),
        sa.Column("document_type", sa.String(length=50), nullable=False),
        sa.Column("reference", sa.String(length=100), nullable=False),
        sa.Column("student_name", sa.String(length=200), nullable=False),
        sa.Column("class_name", sa.String(length=100), nullable=True),
        sa.Column("academic_year", sa.String(length=50), nullable=True),
        sa.Column("student_id", sa.BigInteger(), nullable=True),
        sa.Column("issued_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_document_issuances_token", "document_issuances", ["token"], unique=True)
    op.create_index(
        "ix_document_issuances_cev_code", "document_issuances", ["cev_code"], unique=True
    )
    op.create_index("ix_document_issuances_student_id", "document_issuances", ["student_id"])


def downgrade() -> None:
    op.drop_index("ix_document_issuances_student_id", table_name="document_issuances")
    op.drop_index("ix_document_issuances_cev_code", table_name="document_issuances")
    op.drop_index("ix_document_issuances_token", table_name="document_issuances")
    op.drop_table("document_issuances")
