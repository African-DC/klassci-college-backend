"""school_holidays — calendrier des congés et jours fériés par année scolaire

Alternative B (KLASSCI College 2026-07-03) : le cahier de texte exclut déjà les
grandes vacances (intervalles hors-trimestre). Cette table ajoute les congés en
plein trimestre (Toussaint, fêtes mobiles, jour férié isolé), saisis par
l'établissement car les dates varient chaque année.

Revision ID: 0033_school_holidays
Revises: 0032_document_issuances
Create Date: 2026-07-03
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0033_school_holidays"
down_revision = "0032_document_issuances"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "school_holidays",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("academic_year_id", sa.BigInteger(), nullable=False),
        sa.Column("label", sa.String(length=100), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["academic_year_id"], ["academic_years.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_school_holidays_academic_year_id",
        "school_holidays",
        ["academic_year_id"],
    )


def downgrade() -> None:
    # DROP TABLE supprime aussi ses index. Ne pas DROP INDEX avant : en MySQL
    # l'index de la colonne FK est requis par la contrainte et son retrait échoue.
    op.drop_table("school_holidays")
