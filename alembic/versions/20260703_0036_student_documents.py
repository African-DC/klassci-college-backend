"""Pièces jointes élève : tables document_types + student_documents.

Permet à l'administration de téléverser des documents (extrait de naissance,
etc.) sur la fiche d'un élève, avec un type sélectionnable ou créé à la volée.

Revision ID: 0036_student_documents
Revises: 0035_notification_prefs
Create Date: 2026-07-03
"""

import sqlalchemy as sa

from alembic import op

revision = "0036_student_documents"
down_revision = "0035_notification_prefs"
branch_labels = None
depends_on = None


_DEFAULT_TYPES = [
    "Extrait de naissance",
    "Certificat de résidence",
    "Photo d'identité",
    "Bulletin de l'année précédente",
    "Certificat médical",
    "Fiche d'inscription",
    "Autre",
]


def upgrade() -> None:
    op.create_table(
        "document_types",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    op.create_table(
        "student_documents",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("student_id", sa.BigInteger(), nullable=False),
        sa.Column("document_type", sa.String(length=150), nullable=False),
        sa.Column("file_url", sa.String(length=500), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=True),
        sa.Column("mime_type", sa.String(length=100), nullable=True),
        sa.Column("uploaded_by", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["uploaded_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_student_documents_student_id", "student_documents", ["student_id"])

    values_sql = ", ".join(f"('{name.replace(chr(39), chr(39) * 2)}')" for name in _DEFAULT_TYPES)
    op.execute(f"INSERT IGNORE INTO document_types (name) VALUES {values_sql}")


def downgrade() -> None:
    # MySQL uses this explicit index to enforce the student foreign key and
    # refuses to drop it independently. Dropping the table removes both.
    op.drop_table("student_documents")
    op.drop_table("document_types")
