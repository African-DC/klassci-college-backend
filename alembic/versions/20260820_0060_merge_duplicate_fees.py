"""Fusionne les frais d'eleves en double laisses par la migration 0052.

## Ce que 0052 a laisse derriere elle

La migration 0052 a repointe les `enrollment_fees` vers la variante conservee
de chaque groupe, puis supprime les variantes en double. Elle n'a jamais fusionne
les `enrollment_fees` eux-memes.

Sur un locataire qui portait des variantes dupliquees, un eleve se retrouve donc
avec deux lignes de frais identiques pointant desormais vers la meme variante :
meme inscription, meme tarif, meme montant. Sa dette est doublee, son echeancier
est double, et le certificat de scolarite de la famille est retenu pour un
impaye qui n'existe pas. Plus rien ne signale ces lignes, puisqu'elles sont
devenues indiscernables.

## Le remede

On garde la ligne la plus ancienne de chaque couple (inscription, tarif) — celle
que les versements referencent le plus souvent — apres avoir repointe vers elle
les allocations qui visaient une doublure. Aucun versement ne perd sa
contrepartie : l'argent reste impute, il l'est sur une seule ligne.

Le total impute peut alors depasser le montant de la ligne conservee, si la
famille a paye sur les deux. Ce n'est pas cree ici, seulement rendu visible :
le trop-percu existait deja, reparti sur deux dettes dont une seule etait due.
Le compte est journalise pour que la caisse puisse le reprendre.

Rejouable sans effet : une base deja fusionnee ne presente plus de doublon.

Revision ID: 0060_merge_duplicate_fees
Revises: 0059_teacher_contract_and_gender
Create Date: 2026-08-20
"""

import logging

from sqlalchemy import text

from alembic import op

logger = logging.getLogger("alembic.runtime.migration")

revision = "0060_merge_duplicate_fees"
down_revision = "0059_teacher_contract_and_gender"
branch_labels = None
depends_on = None

#: La ligne conservee de chaque couple (inscription, tarif) : la plus ancienne.
_KEPT_PER_PAIR = """
    SELECT MIN(id) AS keep_id, enrollment_id, fee_variant_id
    FROM enrollment_fees
    GROUP BY enrollment_id, fee_variant_id
"""


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Repointer les allocations de versement vers la ligne conservee.
    #    Fait avant la suppression : la cle etrangere est en RESTRICT, une
    #    doublure encore referencee bloquerait la migration entiere.
    moved = bind.execute(
        text(
            f"""
            UPDATE payment_allocations pa
            JOIN enrollment_fees dup ON dup.id = pa.enrollment_fee_id
            JOIN ({_KEPT_PER_PAIR}) k
              ON k.enrollment_id = dup.enrollment_id
             AND k.fee_variant_id = dup.fee_variant_id
            SET pa.enrollment_fee_id = k.keep_id
            WHERE pa.enrollment_fee_id <> k.keep_id
            """
        )
    ).rowcount

    # 2. Supprimer les doublures, desormais sans allocation.
    removed = bind.execute(
        text(
            f"""
            DELETE dup FROM enrollment_fees dup
            JOIN ({_KEPT_PER_PAIR}) k
              ON k.enrollment_id = dup.enrollment_id
             AND k.fee_variant_id = dup.fee_variant_id
            WHERE dup.id <> k.keep_id
            """
        )
    ).rowcount

    if removed:
        logger.warning(
            "Frais d'eleves en double fusionnes : %s ligne(s) supprimee(s), "
            "%s allocation(s) de versement repointee(s). "
            "Verifier a la caisse les inscriptions dont le total impute depasse "
            "desormais le montant du frais.",
            removed,
            moved,
        )


def downgrade() -> None:
    """Rien a defaire : on ne recree pas une dette qui n'a jamais ete due.

    Les lignes supprimees etaient des copies exactes ; les ressusciter
    redoublerait la dette des familles concernees.
    """
