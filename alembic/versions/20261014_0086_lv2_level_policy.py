"""Disponibilité LV2 par niveau, isolée dans la base de chaque tenant.

La conversion des anciens niveaux utilise exceptionnellement leurs libellés
historiques à l'INSTALLATION (le schéma ne disposait d'aucun code stable).
Toute décision après migration repose uniquement sur levels.lv2_enabled.
Aucune valeur d'inscription.lv2 n'est modifiée ici.

Revision ID: 0086_lv2_level_policy
Revises: 0085_fee_discounts
Create Date: 2026-10-14
"""

import re
import unicodedata

import sqlalchemy as sa
from alembic import op

revision = "0086_lv2_level_policy"
down_revision = "0085_fee_discounts"
branch_labels = None
depends_on = None


def _was_forbidden(name: str) -> bool:
    """Convertit UNIQUEMENT l'ancien comportement, sans règle runtime."""
    normalized = "".join(
        c for c in unicodedata.normalize("NFKD", name.casefold().strip())
        if not unicodedata.combining(c)
    )
    return bool(re.match(r"^(?:6(?:e|eme|em)?|5(?:e|eme|em)?|sixieme|cinquieme)(?:\b|$)", normalized))


def upgrade() -> None:
    op.add_column(
        "levels",
        sa.Column("lv2_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id, name FROM levels")).mappings().all()
    for row in rows:
        if _was_forbidden(row["name"]):
            conn.execute(
                sa.text("UPDATE levels SET lv2_enabled = 0 WHERE id = :id"),
                {"id": row["id"]},
            )


def downgrade() -> None:
    # Annule uniquement la configuration. Les inscriptions restent intactes.
    op.drop_column("levels", "lv2_enabled")
