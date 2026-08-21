"""Index de tri pour les listes d'évaluations et de bulletins.

Les deux listes revenaient en quatre secondes et demie parce qu'elles
rapatriaient toute l'école. Une fois la pagination posée, MySQL ne lit plus
que vingt lignes, mais il doit encore trier l'ensemble avant de les découper
si aucun index ne porte l'ordre demandé.

- `evaluations` : l'écran filtre sur la classe et le trimestre, puis trie par
  date décroissante. Les colonnes portaient trois index isolés, dont aucun ne
  couvrait la combinaison ; l'index composite évite le tri en mémoire.
- `bulletins` : l'ordre par défaut est (année, trimestre, rang). Aucun index
  ne le portait, donc un tri complet des 2 148 bulletins précédait chaque
  page. `rank` est nullable et MySQL place les NULL en tête d'index, ce qui
  correspond au `rank IS NULL` déjà présent dans la clause ORDER BY.

Aucune donnée touchée : ce sont deux CREATE INDEX, réversibles.

Revision ID: 0065_grade_list_indexes
Revises: 0064_cash_auto_closure
Create Date: 2026-08-21
"""

import sqlalchemy as sa

from alembic import op

revision = "0065_grade_list_indexes"
down_revision = "0064_cash_auto_closure"
branch_labels = None
depends_on = None


def _index_exists(nom: str, table: str) -> bool:
    """MySQL 8 ne connait pas `DROP INDEX IF EXISTS` : on demande d'abord."""
    bind = op.get_bind()
    trouve = bind.execute(
        sa.text(
            "SELECT 1 FROM information_schema.STATISTICS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t AND INDEX_NAME = :i "
            "LIMIT 1"
        ),
        {"t": table, "i": nom},
    ).scalar()
    return trouve is not None


def upgrade() -> None:
    op.create_index(
        "idx_evaluations_class_trimester_date",
        "evaluations",
        ["class_id", "trimester", "date"],
    )
    op.create_index(
        "idx_bulletins_year_trimester_rank",
        "bulletins",
        ["academic_year_id", "trimester", "rank"],
    )
    # Le `downgrade` pose un index dedie pour garder la cle etrangere couverte.
    # Une fois le composite recree, il fait double emploi : le retirer rend la
    # base identique qu'on y arrive a neuf ou par un aller-retour.
    if _index_exists("idx_bulletins_academic_year_id", "bulletins"):
        op.drop_index("idx_bulletins_academic_year_id", table_name="bulletins")


def downgrade() -> None:
    # `idx_bulletins_year_trimester_rank` commence par `academic_year_id`, qui
    # porte une cle etrangere. En le creant, MySQL a supprime l'index qu'il
    # avait genere lui-meme pour cette cle : le composite est devenu le seul a
    # la couvrir, et MySQL refuse alors qu'on le retire — erreur 1553,
    # « needed in a foreign key constraint ». On rend donc a la cle un index a
    # elle AVANT de retirer le composite, sans quoi tout `downgrade` casse, et
    # avec lui le provisionnement d'un etablissement, qui rejoue la chaine.
    #
    # `evaluations` n'a pas ce probleme : elle porte deja son propre
    # `idx_evaluations_class_id`, declare a la creation de la table.
    if not _index_exists("idx_bulletins_academic_year_id", "bulletins"):
        op.create_index("idx_bulletins_academic_year_id", "bulletins", ["academic_year_id"])
    op.drop_index("idx_bulletins_year_trimester_rank", table_name="bulletins")
    op.drop_index("idx_evaluations_class_trimester_date", table_name="evaluations")
