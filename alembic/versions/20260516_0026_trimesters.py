"""Trimesters scoped to academic_year.

Calendrier scolaire ivoirien : 3 trimestres par année académique.
Chaque trimestre porte (label, ordre, dates début/fin). Référencés par
les bulletins, conseils de classe et moyennes périodiques.

Revision ID: 0026
Revises: 0025
Create Date: 2026-05-16
"""

import sqlalchemy as sa

from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "trimesters",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("academic_year_id", sa.BigInteger(), nullable=False),
        sa.Column("label", sa.String(50), nullable=False),
        sa.Column("order_no", sa.Integer(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
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
            ["academic_year_id"], ["academic_years.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("academic_year_id", "order_no"),
    )
    op.create_index("idx_trimesters_academic_year_id", "trimesters", ["academic_year_id"])


def downgrade() -> None:
    op.drop_index("idx_trimesters_academic_year_id", table_name="trimesters")
    op.drop_table("trimesters")
