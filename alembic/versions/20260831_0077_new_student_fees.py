"""Tarifs reserves aux nouveaux eleves, et le profil de l'inscription qui les declenche.

Ce qu'un nouvel arrivant paie a son entree — le dossier cartonne, le badge,
la premiere dotation de tenue — un ancien ne le repaie pas. Le tarif gagne
donc une dimension de plus, `enrollment_profile`, calquee sur
`assignment_scope` : deux valeurs, `nouveau` et `ancien`, et `NULL` pour
« s'applique a tout le monde ».

## Retro-compatibilite

Les deux colonnes sont NULL par defaut. Les grilles deja configurees ne
portent aucun profil, donc continuent de s'appliquer a tout le monde, et
aucune famille ne voit ses frais changer.

Ne PAS remplir `enrollments.is_new_student` a `false` en masse. Un
etablissement dont les annees passees ne sont pas reconstituees n'a aucun
moyen de savoir qui est nouveau : trancher a sa place facturerait les frais
d'entree a tous ses anciens eleves, et la famille le decouvrirait sur sa
facture. `NULL` veut dire « on n'a pas tranche », et une inscription a `NULL`
ne recoit aucun tarif porteur d'un profil.

## La contrainte d'unicite

`profile_key` entre dans `uq_fee_variant_dimensions`, sans quoi une ecole ne
pourrait pas definir un tarif « nouveau » ET un tarif general pour la meme
categorie et le meme niveau, ce qui est precisement le but. La contrainte est
reconstruite : on ne peut pas ajouter une colonne a un index unique existant.
L'ajout ne peut creer aucun conflit, toutes les lignes existantes ayant le
meme `profile_key` vide.

Le downgrade, lui, retire une colonne de la cle : deux tarifs qui ne se
distinguaient que par leur profil deviendraient des doublons. Il les fusionne
donc avant, en repointant les frais d'eleves vers la ligne conservee, comme
la migration 0052 l'a fait pour la portee. Aucun frais d'eleve n'est supprime,
donc aucun versement ne perd sa contrepartie.

Revision ID: 0077_new_student_fees
Revises: 0076_in_kind_deposits
Create Date: 2026-08-31
"""

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import text

from alembic import op

logger = logging.getLogger("alembic.runtime.migration")

revision: str = "0077_new_student_fees"
down_revision: str | None = "0076_in_kind_deposits"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX = "uq_fee_variant_dimensions"
_DIMENSIONS_AVEC_PROFIL = [
    "fee_category_id",
    "academic_year_id",
    "level_key",
    "series_key",
    "scope_key",
    "profile_key",
]
_DIMENSIONS_SANS_PROFIL = _DIMENSIONS_AVEC_PROFIL[:-1]

_PROFILE = sa.Enum("nouveau", "ancien", name="fee_enrollment_profile")

#: Les groupes de tarifs qui redeviennent des doublons une fois le profil
#: retire de la cle. On conserve le plus petit id : la ligne d'origine, celle
#: que les frais d'eleves referencent deja dans la grande majorite des cas.
_GROUPES_SANS_PROFIL = """
    SELECT MIN(id) AS keep_id, fee_category_id, academic_year_id,
           COALESCE(level_id, 0) AS lvl, COALESCE(series_id, 0) AS ser,
           COALESCE(assignment_scope, '') AS scope
    FROM fee_variants
    GROUP BY fee_category_id, academic_year_id, lvl, ser, scope
"""

_JOINTURE_SANS_PROFIL = """
      ON k.fee_category_id = dup.fee_category_id
     AND k.academic_year_id = dup.academic_year_id
     AND k.lvl = COALESCE(dup.level_id, 0)
     AND k.ser = COALESCE(dup.series_id, 0)
     AND k.scope = COALESCE(dup.assignment_scope, '')
"""


def upgrade() -> None:
    op.add_column("fee_variants", sa.Column("enrollment_profile", _PROFILE, nullable=True))
    op.create_index("idx_fee_variants_enrollment_profile", "fee_variants", ["enrollment_profile"])
    op.execute(
        "ALTER TABLE fee_variants "
        "ADD COLUMN profile_key VARCHAR(20) AS (COALESCE(enrollment_profile, '')) STORED"
    )

    op.drop_constraint(_INDEX, "fee_variants", type_="unique")
    op.create_unique_constraint(_INDEX, "fee_variants", _DIMENSIONS_AVEC_PROFIL)

    op.add_column("enrollments", sa.Column("is_new_student", sa.Boolean(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()

    # 1. Repointer les frais d'eleves vers la variante conservee de leur groupe.
    bind.execute(
        text(
            f"""
            UPDATE enrollment_fees ef
            JOIN fee_variants dup ON dup.id = ef.fee_variant_id
            JOIN ({_GROUPES_SANS_PROFIL}) k
            {_JOINTURE_SANS_PROFIL}
            SET ef.fee_variant_id = k.keep_id
            WHERE ef.fee_variant_id <> k.keep_id
            """
        )
    )

    # 2. Supprimer les doublures, desormais orphelines.
    removed = bind.execute(
        text(
            f"""
            DELETE dup FROM fee_variants dup
            JOIN ({_GROUPES_SANS_PROFIL}) k
            {_JOINTURE_SANS_PROFIL}
            WHERE dup.id <> k.keep_id
            """
        )
    ).rowcount
    if removed:
        logger.warning(
            "Tarifs a profil fusionnes avec leur tarif general : %s (frais d'eleves repointes)",
            removed,
        )

    op.drop_column("enrollments", "is_new_student")

    op.drop_constraint(_INDEX, "fee_variants", type_="unique")
    op.create_unique_constraint(_INDEX, "fee_variants", _DIMENSIONS_SANS_PROFIL)

    op.execute("ALTER TABLE fee_variants DROP COLUMN profile_key")
    op.drop_index("idx_fee_variants_enrollment_profile", table_name="fee_variants")
    op.drop_column("fee_variants", "enrollment_profile")
