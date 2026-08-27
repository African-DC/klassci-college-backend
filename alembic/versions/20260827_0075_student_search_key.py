"""Un élève porte la forme comparable de son nom, au lieu qu'on la recalcule.

La recherche de doublons repliait les accents et la ponctuation dans la requête
elle-même : 54 `replace()` imbriqués, répliqués quatre fois dans le même arbre
d'analyse, soit 216 appels dans le SQL compilé.

Cette requête était illisible, inutilisable par un index, et la CI l'a refusée
net le 2026-08-27 (run 33086041547) : `sqlite3.OperationalError: parser stack
overflow`, vingt tests tombés. Elle passe pourtant sur d'autres builds de
SQLite, dont celui du poste de développement — la pile d'analyse grandit
dynamiquement chez les uns et pas chez les autres. Le repliage était donc au
bord d'une limite qui dépend de la machine, ce qui est pire qu'au-delà.

Ce n'est pas la meilleure raison de stocker cette forme, seulement la plus
bruyante. La vraie : le repliage vivait en deux exemplaires, un en SQL et un en
Python, qui avaient fini par ne plus dire la même chose — un nom enregistré
avec « œ » était introuvable. Écrite une seule fois, à l'écriture, la règle ne
peut plus diverger d'elle-même.

Ce que ces colonnes n'apportent pas : de la vitesse sur la recherche floue. Le
motif compile un `LIKE '%...%'`, joker en tête, qui reste un balayage. Leurs
index ne servent que la recherche par égalité, celle des noms de trois lettres
ou moins.

ORDRE DE DÉPLOIEMENT — cette migration AVANT le nouveau code. Le code neuf lit
`last_name_key` : déployé avant la migration, toute vérification de doublon rend
500. L'ordre inverse est sans danger : les colonnes sont `NOT NULL` sans défaut,
donc un `INSERT` de l'ancien code, qui ne les connaît pas, échoue avec
« Field 'last_name_key' doesn't have a default value » au lieu d'enregistrer un
élève invisible. Les deux fenêtres sont bruyantes ; aucune ne laisse passer une
fiche muette.

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

_LARGEUR = 200


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
        sa.Column("last_name_key", sa.String(length=_LARGEUR), nullable=False, server_default=""),
    )
    op.add_column(
        "students",
        sa.Column("first_name_key", sa.String(length=_LARGEUR), nullable=False, server_default=""),
    )

    _remplir(op.get_bind())

    for colonne in ("last_name_key", "first_name_key"):
        op.alter_column(
            "students",
            colonne,
            existing_type=sa.String(length=_LARGEUR),
            existing_nullable=False,
            server_default=None,
        )

    op.create_index("ix_students_last_name_key", "students", ["last_name_key"])
    op.create_index("ix_students_first_name_key", "students", ["first_name_key"])


def downgrade() -> None:
    op.drop_index("ix_students_first_name_key", table_name="students")
    op.drop_index("ix_students_last_name_key", table_name="students")
    op.drop_column("students", "first_name_key")
    op.drop_column("students", "last_name_key")
