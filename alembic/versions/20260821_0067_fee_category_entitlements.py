"""Ce qu'une catégorie de frais donne droit, élément par élément.

Ajoute `fee_categories.entitlements`, une liste JSON de `{label, quantity,
kind}`. La colonne existante `description` reste : elle porte la note libre
que le secrétariat écrit pour lui-même, la nouvelle porte ce qui se rend à la
famille et s'imprime sur un reçu.

AUCUN rétro-remplissage. Les écoles déjà en production ont écrit leur
contrepartie en texte libre, et découper ces phrases automatiquement
produirait des éléments faux sur une pièce opposable. Le reçu retombe sur
`description` tant que la liste est vide : rien n'est perdu, et ce qui est
saisi ensuite prend le dessus.

`nullable=True` sans valeur par défaut : les lignes existantes restent à NULL,
que la lecture traite comme « rien de promis ».

Revision ID: 0065_fee_category_entitlements
Revises: 0066_drop_bulletins_year_ix
Create Date: 2026-08-21
"""

import sqlalchemy as sa

from alembic import op

revision = "0067_fee_category_entitlements"
down_revision = "0066_drop_bulletins_year_ix"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("fee_categories", sa.Column("entitlements", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("fee_categories", "entitlements")
