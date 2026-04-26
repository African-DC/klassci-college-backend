"""Add audit field grades.entered_by_user_id for delegation tracking.

Quand un admin saisit les notes au nom d'un prof (workflow réel CI où
les profs 50+ ans donnent leur feuille papier au secrétariat), on doit
tracer QUI a vraiment saisi pour audit légal sur les bulletins signés.

Le champ est nullable car les notes existantes (avant cette migration)
n'ont pas cette info, et les futures notes peuvent rester NULL si le
PATCH endpoint ne le set pas (backward compat).

Revision ID: 0019
Revises: 0018
Create Date: 2026-04-26
"""

from alembic import op
import sqlalchemy as sa


revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "grades",
        sa.Column("entered_by_user_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_grades_entered_by_user_id",
        "grades",
        "users",
        ["entered_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_grades_entered_by_user_id",
        "grades",
        ["entered_by_user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_grades_entered_by_user_id", table_name="grades")
    op.drop_constraint("fk_grades_entered_by_user_id", "grades", type_="foreignkey")
    op.drop_column("grades", "entered_by_user_id")
