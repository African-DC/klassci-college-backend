"""Index de tri pour les listes d'évaluations et de bulletins.

Les deux listes revenaient en quatre secondes et demie parce qu'elles
rapatriaient toute l'école. Une fois la pagination posée, MySQL ne lit plus
que vingt lignes, mais il doit encore trier l'ensemble avant de les découper
si aucun index ne porte l'ordre demandé.

- `evaluations` : l'écran filtre sur la classe et le trimestre, puis trie par
  date décroissante. Les colonnes portaient trois index isolés, dont aucun ne
  couvrait la combinaison ; l'index composite évite le tri en mémoire.
Un index composite avait aussi été posé sur `bulletins (academic_year_id,
trimester, rank)` pour l'ordre par défaut de la liste. Il est retiré ici, avant
sa première diffusion, parce qu'il n'est pas réversible : `bulletins` ne portait
aucun index propre sur `academic_year_id`, seulement celui qu'InnoDB crée pour
la clé étrangère, et InnoDB supprime le sien dès qu'un index utilisateur commence
par cette colonne. Le composite devenait donc le seul à servir la contrainte, et
son `DROP INDEX` échouait en `1553, needed in a foreign key constraint`. Le gain
ne le justifiait pas : trier 2 148 lignes ne coûtait rien face aux 2,5 Mo que la
pagination a supprimés, et l'écran filtre toujours par classe, ce que
`idx_bulletins_class_id` couvre déjà.

`evaluations` n'a pas ce défaut : `idx_evaluations_class_id` existe et continue
de servir la clé étrangère quand le composite est retiré.

Aucune donnée touchée : un CREATE INDEX, réversible.

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


def downgrade() -> None:
    op.drop_index("idx_evaluations_class_trimester_date", table_name="evaluations")
