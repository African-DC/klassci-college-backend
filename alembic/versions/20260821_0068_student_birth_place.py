"""Lieu de naissance de l'élève.

Sur les pièces officielles ivoiriennes — certificat de scolarité, attestation
de fréquentation, fiche d'inscription — un élève est identifié par la formule
« né(e) le ... à ... ». KLASSCI ne collectait que la date : le certificat
imprimait jusqu'ici la **ville de résidence** à la place du lieu de naissance,
ce qui est faux dès qu'un élève né à Bouaké habite Cocody.

La colonne est nullable : les dossiers déjà saisis ne portent pas
l'information et une école doit pouvoir continuer à travailler sans elle. Pas
de rétro-remplissage — recopier `city` reconduirait précisément l'erreur que
cette migration corrige.

`VARCHAR(150)` : les lieux de naissance réels sont parfois longs
(« Bouaké, Sous-préfecture de Djébonoua ») ; 150 laisse la marge sans être
laxiste.

Revision ID: 0065_student_birth_place
Revises: 0067_fee_category_entitlements
Create Date: 2026-08-21
"""

import sqlalchemy as sa

from alembic import op

revision = "0068_student_birth_place"
down_revision = "0067_fee_category_entitlements"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("students", sa.Column("birth_place", sa.String(150), nullable=True))


def downgrade() -> None:
    op.drop_column("students", "birth_place")
