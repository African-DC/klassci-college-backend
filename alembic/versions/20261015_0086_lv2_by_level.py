"""Politique LV2 portée par les niveaux de la base de chaque établissement.

Backfill déterministe sur l'ordre canonique des niveaux préexistants :
1 = 6ème, 2 = 5ème (voir référentiel seed). Aucun libellé n'est consulté.
Vérifier en préproduction les établissements dont l'ordre a été personnalisé.
Les inscriptions, leur LV2 et les exports ne sont jamais touchés.

Revision ID: 0086_lv2_by_level
Revises: 0085_fee_discounts
"""
import sqlalchemy as sa
from alembic import op

revision = "0086_lv2_by_level"
down_revision = "0085_fee_discounts"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column("levels", sa.Column("lv2_enabled", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.execute("UPDATE levels SET lv2_enabled = 0 WHERE `order` IN (1, 2)")

def downgrade() -> None:
    # Perte de la configuration uniquement ; aucune LV2 d'inscription n'est altérée.
    op.drop_column("levels", "lv2_enabled")
