"""Statut d'affectation : la ligne la plus structurante d'une grille ivoirienne.

En Cote d'Ivoire, un eleve affecte dans un etablissement prive est
subventionne par l'Etat : sa famille paie sensiblement moins qu'un non
affecte. Jusqu'ici KLASSCI ignorait la distinction, donc les deux payaient
la meme chose.

Trois valeurs sur l'inscription — l'affectation vaut pour une annee et un
etablissement donnes, un redoublant peut la perdre — et deux seulement sur
le tarif, un reaffecte etant subventionne comme un affecte.

## Retro-compatibilite

Les colonnes sont NULL par defaut, et un tarif sans portee s'applique a tout
le monde : les grilles deja configurees continuent donc de fonctionner sans
qu'on y touche, et aucune famille ne voit ses frais changer. Le jour ou
l'ecole cree un tarif « affecte », seules les inscriptions dont le statut est
renseigne le recevront.

Ne PAS remplir les inscriptions existantes a « non affecte » : ce serait
choisir a la place de l'ecole, et la famille le decouvrirait sur sa facture.

Revision ID: 0051_assignment_status
Revises: 0050_accountant_referentiel
Create Date: 2026-08-20
"""

import sqlalchemy as sa

from alembic import op

revision = "0051_assignment_status"
down_revision = "0050_accountant_referentiel"
branch_labels = None
depends_on = None

_ASSIGNMENT = sa.Enum("affecte", "reaffecte", "non_affecte", name="assignment_status")
_SCOPE = sa.Enum("affecte", "non_affecte", name="fee_assignment_scope")


def upgrade() -> None:
    op.add_column("enrollments", sa.Column("assignment_status", _ASSIGNMENT, nullable=True))
    op.add_column(
        "enrollments", sa.Column("assignment_decision_number", sa.String(50), nullable=True)
    )
    op.create_index("idx_enrollments_assignment_status", "enrollments", ["assignment_status"])

    op.add_column("fee_variants", sa.Column("assignment_scope", _SCOPE, nullable=True))
    op.create_index("idx_fee_variants_assignment_scope", "fee_variants", ["assignment_scope"])

    # La portee entre dans la cle d'unicite : sans elle, une ecole ne pourrait
    # pas definir un tarif affecte ET un tarif non affecte pour le meme
    # niveau, ce qui est precisement le but.
    op.drop_constraint(
        "uq_fee_variant_category_level_series_year", "fee_variants", type_="unique"
    )
    op.create_unique_constraint(
        "uq_fee_variant_category_level_series_year",
        "fee_variants",
        ["fee_category_id", "level_id", "series_id", "assignment_scope", "academic_year_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_fee_variant_category_level_series_year", "fee_variants", type_="unique"
    )
    op.create_unique_constraint(
        "uq_fee_variant_category_level_series_year",
        "fee_variants",
        ["fee_category_id", "level_id", "series_id", "academic_year_id"],
    )
    op.drop_index("idx_fee_variants_assignment_scope", table_name="fee_variants")
    op.drop_column("fee_variants", "assignment_scope")

    op.drop_index("idx_enrollments_assignment_status", table_name="enrollments")
    op.drop_column("enrollments", "assignment_decision_number")
    op.drop_column("enrollments", "assignment_status")
