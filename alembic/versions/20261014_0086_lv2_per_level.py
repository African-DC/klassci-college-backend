"""LV2 par niveau, dans la base de chaque tenant.

Revision ID: 0086_level_lv2
Revises: 0085_fee_discounts

Le nom n'est utilise qu'UNE FOIS pour reprendre le comportement historique
des niveaux preexistants. Apres migration, ni serveur ni portail ne decident
en regardant un libelle. Les niveaux aux noms non conventionnels doivent etre
verifies par la direction. Aucune inscription LV2 n'est modifiee.
"""
import re
import unicodedata

from alembic import op
import sqlalchemy as sa

revision = "0086_level_lv2"
down_revision = "0085_fee_discounts"
branch_labels = None
depends_on = None


def _formerly_forbidden(name: str) -> bool:
    normalized = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().strip().lower()
    # Reproduit uniquement la classification historique de 6e / 5e.
    return bool(re.match(r"^(?:6(?:e|eme)?|5(?:e|eme)?|sixieme|cinquieme)(?:\\b|[_\\s-])", normalized))


def upgrade() -> None:
    op.add_column("levels", sa.Column("lv2_enabled", sa.Boolean(), nullable=False, server_default=sa.true()))
    conn = op.get_bind()
    levels = conn.execute(sa.text("SELECT id, name FROM levels")).all()
    for level_id, name in levels:
        if _formerly_forbidden(name or ""):
            conn.execute(sa.text("UPDATE levels SET lv2_enabled = :enabled WHERE id = :id"), {"enabled": False, "id": level_id})


def downgrade() -> None:
    op.drop_column("levels", "lv2_enabled")
