"""Rend enfin effective l'unicite des tarifs.

## Le probleme

La contrainte `uq_fee_variant_category_level_series_year` existait depuis
l'origine, mais elle n'a jamais protege un seul niveau de college : en SQL,
`NULL` n'est jamais egal a `NULL`. Comme `series_id` est vide sur tous les
niveaux de college — les series n'existent qu'au lycee — deux lignes
identiques ne se sont jamais heurtees.

Constat sur la production Rostan : la categorie « Inscription » portait deux
variantes identiques pour la 6eme et deux pour la 5eme. Chaque ajout creait
un doublon, et l'affichage par niveau en retenait un au hasard : d'ou
l'impression qu'un montant saute d'un niveau a l'autre.

## Le remede

Des colonnes generees remplacent les NULL par des sentinelles, et l'index
unique porte sur elles. MySQL compare alors des valeurs reelles.

## Le dedoublonnage

On garde la ligne la plus ancienne de chaque groupe — c'est celle que les
frais d'eleves referencent le plus souvent — apres avoir repointe vers elle
les frais qui visaient une doublure. Aucun frais d'eleve n'est supprime, donc
aucun versement ne perd sa contrepartie.

Revision ID: 0052_fee_variant_real_uniqueness
Revises: 0051_assignment_status
Create Date: 2026-08-20
"""

import logging

from sqlalchemy import text

from alembic import op

logger = logging.getLogger("alembic.runtime.migration")

revision = "0052_fee_variant_real_uniqueness"
down_revision = "0051_assignment_status"
branch_labels = None
depends_on = None

_OLD_INDEX = "uq_fee_variant_category_level_series_year"
_NEW_INDEX = "uq_fee_variant_dimensions"


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Repointer les frais d'eleves vers la variante conservee de leur groupe.
    #    On conserve le plus petit id : la ligne d'origine, celle que les frais
    #    referencent deja dans la grande majorite des cas.
    bind.execute(
        text(
            """
            UPDATE enrollment_fees ef
            JOIN fee_variants dup ON dup.id = ef.fee_variant_id
            JOIN (
                SELECT MIN(id) AS keep_id, fee_category_id, academic_year_id,
                       COALESCE(level_id, 0) AS lvl, COALESCE(series_id, 0) AS ser,
                       COALESCE(assignment_scope, '') AS scope
                FROM fee_variants
                GROUP BY fee_category_id, academic_year_id, lvl, ser, scope
            ) k
              ON k.fee_category_id = dup.fee_category_id
             AND k.academic_year_id = dup.academic_year_id
             AND k.lvl = COALESCE(dup.level_id, 0)
             AND k.ser = COALESCE(dup.series_id, 0)
             AND k.scope = COALESCE(dup.assignment_scope, '')
            SET ef.fee_variant_id = k.keep_id
            WHERE ef.fee_variant_id <> k.keep_id
            """
        )
    )

    # 2. Supprimer les doublures, desormais orphelines.
    removed = bind.execute(
        text(
            """
            DELETE dup FROM fee_variants dup
            JOIN (
                SELECT MIN(id) AS keep_id, fee_category_id, academic_year_id,
                       COALESCE(level_id, 0) AS lvl, COALESCE(series_id, 0) AS ser,
                       COALESCE(assignment_scope, '') AS scope
                FROM fee_variants
                GROUP BY fee_category_id, academic_year_id, lvl, ser, scope
            ) k
              ON k.fee_category_id = dup.fee_category_id
             AND k.academic_year_id = dup.academic_year_id
             AND k.lvl = COALESCE(dup.level_id, 0)
             AND k.ser = COALESCE(dup.series_id, 0)
             AND k.scope = COALESCE(dup.assignment_scope, '')
            WHERE dup.id <> k.keep_id
            """
        )
    ).rowcount
    if removed:
        logger.warning("Tarifs en double supprimes : %s (frais d'eleves repointes)", removed)

    # 3. Colonnes generees : la base compare des valeurs, plus des NULL.
    op.execute(
        "ALTER TABLE fee_variants "
        "ADD COLUMN level_key BIGINT AS (COALESCE(level_id, 0)) STORED, "
        "ADD COLUMN series_key BIGINT AS (COALESCE(series_id, 0)) STORED, "
        "ADD COLUMN scope_key VARCHAR(20) AS (COALESCE(assignment_scope, '')) STORED"
    )

    op.drop_constraint(_OLD_INDEX, "fee_variants", type_="unique")
    op.create_unique_constraint(
        _NEW_INDEX,
        "fee_variants",
        ["fee_category_id", "academic_year_id", "level_key", "series_key", "scope_key"],
    )


def downgrade() -> None:
    op.drop_constraint(_NEW_INDEX, "fee_variants", type_="unique")
    op.execute(
        "ALTER TABLE fee_variants "
        "DROP COLUMN level_key, DROP COLUMN series_key, DROP COLUMN scope_key"
    )
    op.create_unique_constraint(
        _OLD_INDEX,
        "fee_variants",
        ["fee_category_id", "level_id", "series_id", "assignment_scope", "academic_year_id"],
    )
