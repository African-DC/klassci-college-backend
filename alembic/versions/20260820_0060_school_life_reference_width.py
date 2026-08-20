"""Elargit la reference des actes de vie scolaire a 100 caracteres.

La reference d'un acte porte desormais l'identifiant de l'acte, en plus du
matricule de l'eleve : sans lui, deux billets d'annulation de zero du meme
eleve partageaient leur lignee de sceau et s'invalidaient mutuellement.

Le matricule fait jusqu'a 50 caracteres. Avec le prefixe, l'annee et
l'identifiant, la reference depasse les 60 caracteres de la colonne, et
MySQL en mode strict refuse l'ecriture au moment ou le guichet imprime.
On aligne les deux colonnes sur `document_issuance.reference`, deja en 100.

Revision ID: 0060_school_life_reference_width
Revises: 0059_teacher_contract_and_gender
Create Date: 2026-08-20
"""

import sqlalchemy as sa

from alembic import op

revision = "0060_school_life_reference_width"
down_revision = "0059_teacher_contract_and_gender"
branch_labels = None
depends_on = None

_TABLES = ("parent_summons", "retake_authorizations")


def upgrade() -> None:
    for table in _TABLES:
        op.alter_column(
            table,
            "reference",
            existing_type=sa.String(60),
            type_=sa.String(100),
            existing_nullable=True,
        )


def downgrade() -> None:
    # Retour a 60 : les references trop longues seraient tronquees, donc on
    # les efface plutot que de laisser un papier verifiable pointer vers une
    # reference qui n'existe plus.
    for table in _TABLES:
        op.execute(sa.text(f"UPDATE {table} SET reference = NULL WHERE LENGTH(reference) > 60"))
        op.alter_column(
            table,
            "reference",
            existing_type=sa.String(100),
            type_=sa.String(60),
            existing_nullable=True,
        )
