"""Fusionne les categories « Scolarite Trimestre N » en une categorie « Scolarite ».

Le trimestre est un moment de paiement, pas une nature de frais. Depuis la
migration 0045, le decoupage dans le temps est porte par les tranches
(`fee_installments`), et garder trois categories de scolarite ne fait plus
que dedoubler la meme nature.

Ecrite en Python plutot qu'en SQL brut : la fusion enchaine des lectures et
des ecritures dependantes (regrouper les variantes, sommer, repointer les
frais d'inscription), et un `INSERT ... ON DUPLICATE KEY UPDATE` portable
entre MySQL 8.4 et 9.6 serait bien moins lisible que la boucle equivalente.

## Garde-fous — la migration s'abstient plutot que d'abimer des donnees

1. Aucun paiement ne doit etre impute a un frais de trimestre. Fusionner
   sous de l'argent deja alloue casserait la tracabilite comptable.
2. Aucun frais de trimestre ne doit avoir un statut autre que `pending`.
   Un frais exonere fusionne redeviendrait du.

Si l'un des deux echoue, la migration journalise et s'arrete sans rien
changer, mais se marque appliquee. Lever ici bloquerait la chaine de
migrations de ce tenant pour toujours : plus aucune mise a jour ne passerait.
Un etablissement qui garde ses trimestres n'est pas casse pour autant — les
tranches portent sur le TOTAL, quelles que soient les categories.

Revision ID: 0046_merge_trimester_categories
Revises: 0045_installments
Create Date: 2026-08-20
"""

import logging
from decimal import Decimal

from sqlalchemy import text

from alembic import op

logger = logging.getLogger("alembic.runtime.migration")

revision = "0046_merge_trimester_categories"
down_revision = "0045_installments"
branch_labels = None
depends_on = None

# Couvre « Scolarite Trimestre 1 », « Scolarité Trimestre 1 », « Scolarite T1 ».
_TRIMESTER_PATTERN = "Scolarit% Trimestre%"
_TARGET_NAME = "Scolarité"
# Juste apres l'inscription dans l'ordre d'allocation, place qu'occupaient les
# trimestres.
_TARGET_PRIORITY = 20


def upgrade() -> None:
    bind = op.get_bind()

    category_ids = [
        row[0]
        for row in bind.execute(
            text("SELECT id FROM fee_categories WHERE name LIKE :pattern"),
            {"pattern": _TRIMESTER_PATTERN},
        ).all()
    ]
    if not category_ids:
        return  # Rien a fusionner : etablissement deja au bon modele.

    ids_csv = ", ".join(str(int(cid)) for cid in category_ids)

    blocking_payments = bind.execute(
        text(
            f"""
            SELECT COUNT(*) FROM payment_allocations pa
            JOIN enrollment_fees ef ON ef.id = pa.enrollment_fee_id
            JOIN fee_variants fv ON fv.id = ef.fee_variant_id
            WHERE fv.fee_category_id IN ({ids_csv})
            """
        )
    ).scalar_one()
    if blocking_payments:
        logger.warning(
            "Fusion des categories de trimestre ABANDONNEE : %s versement(s) y sont "
            "imputes. Fusionner casserait la tracabilite comptable. Les trimestres "
            "restent en place — ils fonctionnent, les tranches portent sur le total "
            "quelles que soient les categories. A traiter manuellement.",
            blocking_payments,
        )
        return

    blocking_fees = bind.execute(
        text(
            f"""
            SELECT COUNT(*) FROM enrollment_fees ef
            JOIN fee_variants fv ON fv.id = ef.fee_variant_id
            WHERE fv.fee_category_id IN ({ids_csv})
            AND ef.status <> 'pending'
            """
        )
    ).scalar_one()
    if blocking_fees:
        logger.warning(
            "Fusion des categories de trimestre ABANDONNEE : %s frais ne sont pas au "
            "statut « pending » (exonere, partiel ou solde). Un frais exonere fusionne "
            "redeviendrait du. Les trimestres restent en place.",
            blocking_fees,
        )
        return

    # 1. Categorie cible, creee si absente.
    target_id = bind.execute(
        text("SELECT id FROM fee_categories WHERE name = :name"), {"name": _TARGET_NAME}
    ).scalar_one_or_none()
    if target_id is None:
        bind.execute(
            text(
                "INSERT INTO fee_categories (name, is_mandatory, priority, created_at, updated_at) "
                "VALUES (:name, 1, :priority, NOW(), NOW())"
            ),
            {"name": _TARGET_NAME, "priority": _TARGET_PRIORITY},
        )
        target_id = bind.execute(
            text("SELECT id FROM fee_categories WHERE name = :name"), {"name": _TARGET_NAME}
        ).scalar_one()

    # 2. Une variante fusionnee par (annee, niveau, serie), montant = somme.
    groups = bind.execute(
        text(
            f"""
            SELECT academic_year_id, level_id, series_id, SUM(amount)
            FROM fee_variants
            WHERE fee_category_id IN ({ids_csv})
            GROUP BY academic_year_id, level_id, series_id
            """
        )
    ).all()

    merged_variant_by_group: dict[tuple[int, int | None, int | None], int] = {}
    for year_id, level_id, series_id, total in groups:
        params = {
            "cat": target_id,
            "year": year_id,
            "level": level_id,
            "series": series_id,
            "amount": Decimal(str(total or 0)),
        }
        existing = bind.execute(
            text(
                "SELECT id, amount FROM fee_variants "
                "WHERE fee_category_id = :cat AND academic_year_id = :year "
                "AND level_id <=> :level AND series_id <=> :series"
            ),
            params,
        ).first()

        if existing is None:
            bind.execute(
                text(
                    "INSERT INTO fee_variants "
                    "(fee_category_id, academic_year_id, amount, level_id, series_id, "
                    " created_at, updated_at) "
                    "VALUES (:cat, :year, :amount, :level, :series, NOW(), NOW())"
                ),
                params,
            )
            variant_id = bind.execute(text("SELECT LAST_INSERT_ID()")).scalar_one()
        else:
            # Une « Scolarite » existait deja pour ce groupe : on additionne
            # plutot que d'ecraser, sinon le montant des trimestres serait perdu.
            variant_id = existing[0]
            bind.execute(
                text("UPDATE fee_variants SET amount = amount + :amount WHERE id = :id"),
                {"amount": params["amount"], "id": variant_id},
            )

        merged_variant_by_group[(year_id, level_id, series_id)] = int(variant_id)

    # 3. Repointer les frais d'inscription : les N lignes de trimestre d'une
    #    inscription deviennent UNE ligne sur la variante fusionnee.
    fee_rows = bind.execute(
        text(
            f"""
            SELECT ef.enrollment_id, fv.academic_year_id, fv.level_id, fv.series_id,
                   SUM(ef.amount)
            FROM enrollment_fees ef
            JOIN fee_variants fv ON fv.id = ef.fee_variant_id
            WHERE fv.fee_category_id IN ({ids_csv})
            GROUP BY ef.enrollment_id, fv.academic_year_id, fv.level_id, fv.series_id
            """
        )
    ).all()

    bind.execute(
        text(
            f"""
            DELETE ef FROM enrollment_fees ef
            JOIN fee_variants fv ON fv.id = ef.fee_variant_id
            WHERE fv.fee_category_id IN ({ids_csv})
            """
        )
    )

    for enrollment_id, year_id, level_id, series_id, total in fee_rows:
        variant_id = merged_variant_by_group.get((year_id, level_id, series_id))
        if variant_id is None:
            continue
        bind.execute(
            text(
                "INSERT INTO enrollment_fees "
                "(enrollment_id, fee_variant_id, amount, status, created_at, updated_at) "
                "VALUES (:enrollment, :variant, :amount, 'pending', NOW(), NOW())"
            ),
            {
                "enrollment": enrollment_id,
                "variant": variant_id,
                "amount": Decimal(str(total or 0)),
            },
        )

    # 4. Les anciennes variantes et categories n'ont plus de referent.
    bind.execute(text(f"DELETE FROM fee_variants WHERE fee_category_id IN ({ids_csv})"))
    bind.execute(text(f"DELETE FROM fee_categories WHERE id IN ({ids_csv})"))


def downgrade() -> None:
    # Irreversible : on ne sait pas redecouper une somme en trois trimestres
    # dont on a perdu les montants d'origine. Inventer un tiers pour chacun
    # serait pire que de ne rien faire.
    pass
