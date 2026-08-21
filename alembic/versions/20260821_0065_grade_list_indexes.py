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

from alembic import op

revision = "0065_grade_list_indexes"
down_revision = "0064_cash_auto_closure"
branch_labels = None
depends_on = None


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


def downgrade() -> None:
    op.drop_index("idx_bulletins_year_trimester_rank", table_name="bulletins")
    op.drop_index("idx_evaluations_class_trimester_date", table_name="evaluations")
