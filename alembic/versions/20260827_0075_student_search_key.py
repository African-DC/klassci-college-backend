"""Un élève porte la forme comparable de son nom, au lieu qu'on la recalcule.

La recherche de doublons repliait les accents et la ponctuation dans la requête
elle-même : 54 `replace()` imbriqués, répliqués quatre fois dans le même arbre
d'analyse — une fois par expression du `OR`. SQLite refusait de l'analyser, son
analyseur plafonnant à une centaine de niveaux d'imbrication cumulée, et vingt
tests tombaient sur un débordement de pile.

Le repliage existait surtout en deux exemplaires, un en SQL et un en Python,
qui avaient déjà divergé : un nom enregistré avec « œ » était introuvable.

Les deux colonnes ajoutées ici portent cette forme une fois pour toutes, et le
modèle les tient à jour à chaque écriture du nom. Le remplissage des fiches
existantes passe par la fonction Python, la même que celle qui servira ensuite,
pour qu'aucune fiche d'aujourd'hui ne réponde autrement qu'une fiche de demain.

Ce que ces colonnes n'apportent PAS : de la vitesse. Leurs index ne servent que
la recherche par égalité, celle des noms de trois lettres ou moins. La
recherche courante compile un `LIKE '%...%'`, joker en tête, qui reste un
balayage. Le gain est la lisibilité de la requête et l'unicité de la règle.

ORDRE DE DÉPLOIEMENT — cette migration AVANT le nouveau code, et sans fenêtre
d'écriture entre les deux. Le code neuf lit `last_name_key` : déployé avant la
migration, toute vérification de doublon rend 500 (panne bruyante, immédiate).
Migration jouée mais ancien code encore en place, les élèves créés pendant la
fenêtre reçoivent une clé vide et deviennent invisibles à la détection dès que
le code neuf arrive — panne muette, celle-là. Si la fenêtre a existé, rattraper
avec la boucle de `_remplir` sur les lignes dont la clé est vide.

Revision ID: 0075_student_search_key
Revises: 0074_enrol_validate_perm
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.core.names import compact

revision: str = "0075_student_search_key"
down_revision: str | None = "0074_enrol_validate_perm"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _remplir(connexion: sa.Connection) -> None:
    """Calcule la clé des fiches existantes, par la fonction Python.

    Pas par du SQL : c'est la seule façon de garantir que les fiches déjà en
    base répondent exactement comme celles qui seront créées ensuite. Un
    repliage SQL écrit ici serait un troisième exemplaire de la règle, et le
    troisième aurait divergé aussi.
    """
    fiches = connexion.execute(sa.text("SELECT id, last_name, first_name FROM students")).fetchall()
    if not fiches:
        return
    connexion.execute(
        sa.text(
            "UPDATE students SET last_name_key = :nom, first_name_key = :prenom WHERE id = :id"
        ),
        [
            {"nom": compact(nom), "prenom": compact(prenom), "id": identifiant}
            for identifiant, nom, prenom in fiches
        ],
    )


def upgrade() -> None:
    # Le defaut serveur n'existe que pour l'ALTER TABLE sur les lignes deja
    # presentes. Il est retire juste apres : sans ce retrait, un futur INSERT
    # qui oublierait les deux colonnes reussirait en silence avec une cle vide,
    # et l'eleve serait invisible a la detection — exactement le contournement
    # qu'on cherche a rendre impossible.
    op.add_column(
        "students",
        sa.Column("last_name_key", sa.String(length=100), nullable=False, server_default=""),
    )
    op.add_column(
        "students",
        sa.Column("first_name_key", sa.String(length=100), nullable=False, server_default=""),
    )

    _remplir(op.get_bind())

    op.alter_column(
        "students", "last_name_key", existing_type=sa.String(length=100), server_default=None
    )
    op.alter_column(
        "students", "first_name_key", existing_type=sa.String(length=100), server_default=None
    )

    op.create_index("ix_students_last_name_key", "students", ["last_name_key"])
    op.create_index("ix_students_first_name_key", "students", ["first_name_key"])


def downgrade() -> None:
    op.drop_index("ix_students_first_name_key", table_name="students")
    op.drop_index("ix_students_last_name_key", table_name="students")
    op.drop_column("students", "first_name_key")
    op.drop_column("students", "last_name_key")
