"""Allocation planner & fee status recompute — pures functions, testables.

Le `plan_allocation` est volontairement pur (pas de session DB, pas d'I/O)
pour pouvoir être testé unitaire sans fixtures DB. La règle de
recalcul fee.status est centralisée ici pour être appelée par
`recording.py` (à la création) ET par `lifecycle.py` (cancel/validate).
"""

from collections.abc import Iterable
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fee import EnrollmentFee, EnrollmentFeeStatus
from app.services import fees_paid


def plan_allocation(
    amount: Decimal,
    fees_with_paid: list[tuple[EnrollmentFee, Decimal]],
) -> tuple[list[tuple[EnrollmentFee, Decimal]], Decimal]:
    """Distribue `amount` aux fees par ordre fourni. Retourne (splits, surplus).

    `fees_with_paid` est attendu déjà trié par priorité ASC. Chaque entrée =
    (fee, total_paid_so_far). Cette fonction est pure : aucune I/O DB, aucune
    mutation. Testable unitaire avec des dataclasses synthétiques.
    """
    remaining = amount
    splits: list[tuple[EnrollmentFee, Decimal]] = []
    for fee, paid_so_far in fees_with_paid:
        if remaining <= 0:
            break
        fee_remaining = fee.amount - paid_so_far
        if fee_remaining <= 0:
            continue
        allocated = min(remaining, fee_remaining)
        splits.append((fee, allocated))
        remaining -= allocated
    return splits, remaining


async def paid_for_fees(db: AsyncSession, fees: Iterable[EnrollmentFee]) -> dict[int, Decimal]:
    """Ce qui est versé sur chacun de ces frais, indexé par frais.

    Une requête groupée par inscription — en pratique une seule, puisque les
    allocations d'un versement portent toutes sur la même. Le calcul est celui
    de `fees_paid`, le seul : la caisse ne peut pas voir un montant que la
    famille ne voit pas sur son portail.
    """
    verses: dict[int, Decimal] = {}
    for enrollment_id in {fee.enrollment_id for fee in fees}:
        verses.update(await fees_paid.paid_by_enrollment(db, enrollment_id))
    return verses


def recompute_fee_status(fee: EnrollmentFee, total_paid: Decimal) -> None:
    """Recalcule le status d'un EnrollmentFee à partir de ce qui y est versé.

    Pure : l'appelant fournit le total, obtenu par `paid_for_fees` en une
    requête pour toute l'inscription. La fonction interrogeait auparavant la
    base elle-même, frais par frais — dans une boucle sur les splits d'un
    versement, cela faisait un aller-retour par frais alors qu'un seul suffit.

    Idempotent : appelable après create, validate ou cancel sans état préalable.
    """
    if fee.status == EnrollmentFeeStatus.WAIVED.value:
        return
    if total_paid >= fee.amount:
        fee.status = EnrollmentFeeStatus.PAID.value
    elif total_paid > Decimal("0"):
        fee.status = EnrollmentFeeStatus.PARTIAL.value
    else:
        fee.status = EnrollmentFeeStatus.PENDING.value
