"""Allocation planner & fee status recompute — pures functions, testables.

Le `plan_allocation` est volontairement pur (pas de session DB, pas d'I/O)
pour pouvoir être testé unitaire sans fixtures DB. La règle de
recalcul fee.status est centralisée ici pour être appelée par
`recording.py` (à la création) ET par `lifecycle.py` (cancel/validate).
"""

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fee import EnrollmentFee, EnrollmentFeeStatus
from app.repositories import payment_repository as repo


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


async def recompute_fee_status(db: AsyncSession, fee: EnrollmentFee) -> None:
    """Recalcule le status d'un EnrollmentFee à partir de ses allocations COMPLETED.

    Source de vérité = `payment_allocations` jointures `payments.status='completed'`
    (cf. `repo.get_total_paid_for_enrollment_fee`). Idempotent — peut être
    appelé après create, validate ou cancel sans état préalable.
    """
    if fee.status == EnrollmentFeeStatus.WAIVED.value:
        return
    total_paid = await repo.get_total_paid_for_enrollment_fee(db, fee.id)
    if total_paid >= fee.amount:
        fee.status = EnrollmentFeeStatus.PAID.value
    elif total_paid > Decimal("0"):
        fee.status = EnrollmentFeeStatus.PARTIAL.value
    else:
        fee.status = EnrollmentFeeStatus.PENDING.value
