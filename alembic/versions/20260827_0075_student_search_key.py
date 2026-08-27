"""Un élève porte la forme comparable de son nom, au lieu qu'on la recalcule.

La recherche de doublons repliait les accents et la ponctuation dans la
requête elle-même : 216 `replace()` imbriqués, reconstruits à chaque frappe du
secrétariat. Trois conséquences.

Aucun index ne pouvait servir — la base balayait tout le fichier élèves.
SQLite refusait carrément la requête, son analyseur plafonnant à une centaine
de niveaux d'imbrication. Et le repliage existait en deux exemplaires, un en
SQL et un en Python, qui avaient déjà divergé : un nom enregistré avec « œ »
était introuvable.

Les deux colonnes ajoutées ici portent cette forme une fois pour toutes, et le
modèle les tient à jour à chaque écriture du nom. Le remplissage des fiches
existantes passe par la fonction Python, la même que celle qui servira ensuite,
pour qu'aucune fiche d'aujourd'hui ne réponde autrement qu'une fiche de demain.

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


def upgrade() -> None:
    op.add_column(
        "students",
        sa.Column("last_name_key", sa.String(length=100), nullable=False, server_default=""),
    )
    op.add_column(
        "students",
        sa.Column("first_name_key", sa.String(length=100), nullable=False, server_default=""),
    )

    # Remplissage par la fonction Python, pas par du SQL : c'est la seule
    # facon de garantir que les fiches deja en base repondent exactement comme
    # celles qui seront creees ensuite. Un repliage SQL ecrit ici serait un
    # troisieme exemplaire de la regle, et le troisieme aurait divergé aussi.
    connexion = op.get_bind()
    fiches = connexion.execute(sa.text("SELECT id, last_name, first_name FROM students")).fetchall()
    for identifiant, nom, prenom in fiches:
        connexion.execute(
            sa.text(
                "UPDATE students SET last_name_key = :nom, first_name_key = :prenom WHERE id = :id"
            ),
            {"nom": compact(nom), "prenom": compact(prenom), "id": identifiant},
        )

    op.create_index("ix_students_last_name_key", "students", ["last_name_key"])
    op.create_index("ix_students_first_name_key", "students", ["first_name_key"])


def downgrade() -> None:
    op.drop_index("ix_students_first_name_key", table_name="students")
    op.drop_index("ix_students_last_name_key", table_name="students")
    op.drop_column("students", "first_name_key")
    op.drop_column("students", "last_name_key")
