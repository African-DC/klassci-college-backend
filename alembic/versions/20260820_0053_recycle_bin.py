"""Corbeille sur les fiches qui portent une histoire.

Eleves, parents, enseignants, personnel et inscriptions sont lies a des
personnes reelles et a des annees de donnees : on ne les efface pas d'un
clic. Archiver les retire des ecrans sans rien detruire ; la suppression
definitive ne se fait qu'ensuite, depuis la corbeille.

La configuration — categories de frais, tarifs, niveaux, salles — n'y passe
pas : elle garde la regle deja en place, cascade si rien ne s'en sert, refus
chiffre sinon. Une corbeille pour une categorie creee par erreur il y a
trente secondes ajouterait une etape pour rien.

`archived_at` est la seule source de verite : une fiche est dans la corbeille
si et seulement si cette date est renseignee.

Revision ID: 0053_recycle_bin
Revises: 0052_fee_variant_real_uniqueness
Create Date: 2026-08-20
"""

import sqlalchemy as sa

from alembic import op

revision = "0053_recycle_bin"
down_revision = "0052_fee_variant_real_uniqueness"
branch_labels = None
depends_on = None

_TABLES = ("students", "parents", "teacher_profiles", "staff_profiles", "enrollments")


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(table, sa.Column("archived_at", sa.DateTime(), nullable=True))
        op.add_column(table, sa.Column("archived_by", sa.BigInteger(), nullable=True))
        op.add_column(table, sa.Column("archive_reason", sa.String(500), nullable=True))
        # Toutes les listes filtrent sur cette colonne : sans index, chaque
        # ecran ferait un balayage complet.
        op.create_index(f"idx_{table}_archived_at", table, ["archived_at"])


def downgrade() -> None:
    for table in _TABLES:
        op.drop_index(f"idx_{table}_archived_at", table_name=table)
        op.drop_column(table, "archive_reason")
        op.drop_column(table, "archived_by")
        op.drop_column(table, "archived_at")
