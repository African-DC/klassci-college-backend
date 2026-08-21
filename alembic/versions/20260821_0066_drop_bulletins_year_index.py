"""Retire l'index composite de `bulletins` posé par la 0065.

La 0065 avait posé `idx_bulletins_year_trimester_rank` sur
`bulletins (academic_year_id, trimester, rank)`. Elle a été corrigée pour ne
plus le créer, mais l'index existe déjà partout où elle est passée, dont la
démonstration : c'est ce que cette migration nettoie.

Pourquoi il devait partir : `bulletins` ne portait aucun index propre sur
`academic_year_id`. La création de la table n'en a posé que sur `student_id` et
`class_id`, alors que le modèle déclare les trois. InnoDB avait donc fabriqué le
sien pour la clé étrangère, puis l'a supprimé dès qu'un index utilisateur
commençant par cette colonne est apparu. Le composite restait le seul à servir
la contrainte, et son `DROP INDEX` échouait en `1553, needed in a foreign key
constraint` : la 0065 n'était plus réversible, ce qu'a montré l'étape
« downgrade base » de l'intégration continue.

D'où l'ordre ici : poser d'abord l'index simple que le modèle réclamait depuis
toujours, ce qui rend la clé étrangère indépendante du composite, puis retirer
le composite. Les deux gestes sont conditionnés à l'état réel du schéma, lu au
lieu d'être déduit du chemin de migration emprunté.

Le `downgrade` ne repose rien : remettre le composite reproduirait l'impasse, et
retirer l'index simple casserait la clé étrangère. Une migration qui répare une
impasse n'a pas à savoir y retourner.

Revision ID: 0066_drop_bulletins_year_ix
Revises: 0065_grade_list_indexes
Create Date: 2026-08-21
"""

from sqlalchemy import inspect

from alembic import op

revision = "0066_drop_bulletins_year_ix"
down_revision = "0065_grade_list_indexes"
branch_labels = None
depends_on = None

_COMPOSITE = "idx_bulletins_year_trimester_rank"
_FK_INDEX = "ix_bulletins_academic_year_id"


def upgrade() -> None:
    existing = {index["name"] for index in inspect(op.get_bind()).get_indexes("bulletins")}

    if _FK_INDEX not in existing:
        op.create_index(_FK_INDEX, "bulletins", ["academic_year_id"])

    if _COMPOSITE in existing:
        op.drop_index(_COMPOSITE, table_name="bulletins")


def downgrade() -> None:
    """Sans effet : reposer le composite rendrait de nouveau la 0065 irréversible."""
