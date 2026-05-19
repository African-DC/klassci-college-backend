"""Personnalisation PDF par tenant : primary_color + accent_color + website + motto.

Permet à chaque école de personnaliser l'identité visuelle de ses documents
PDF (bulletins, reçus, attestations) tout en gardant la cohérence design
KLASSCI. Couleurs au format `#RRGGBB`. Fallback sur palette KLASSCI si NULL.

Revision ID: 0029
Revises: 0028
Create Date: 2026-05-18
"""

import sqlalchemy as sa

from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


_COLUMNS = [
    ("primary_color", sa.String(7)),    # hex #RRGGBB — couleur principale école
    ("accent_color", sa.String(7)),     # hex #RRGGBB — accent CTA / highlights
    ("website", sa.String(255)),        # URL site web école
    ("motto", sa.String(255)),          # devise (ex: "Excellence Discipline Travail")
]


def upgrade() -> None:
    for col_name, col_type in _COLUMNS:
        op.add_column(
            "school_settings",
            sa.Column(col_name, col_type, nullable=True),
        )


def downgrade() -> None:
    for col_name, _ in reversed(_COLUMNS):
        op.drop_column("school_settings", col_name)
