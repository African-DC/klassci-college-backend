"""Preview UX caissier — calcule l'allocation sans rien écrire.

Appelé par le FE avant submit pour montrer le breakdown (qui reçoit
combien, surplus éventuel, raison de rejet). Read-only — pas de
verrouillage row, pas de commit.
"""

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessValidationError
from app.models.fee import EnrollmentFee, EnrollmentFeeStatus
from app.repositories import payment_repository as repo
from app.schemas.fee import FeeEntitlement
from app.schemas.payment import AllocationPreviewLine, AllocationPreviewResponse
from app.services import fee_entitlements as entitlements
from app.services import fees_paid
from app.services.payments._allocation import plan_allocation


def _resolve_category(fee: EnrollmentFee) -> tuple[str, int, list[FeeEntitlement]]:
    """Extrait (name, priority, contrepartie) de la category liée. Defaults safe."""
    fv = getattr(fee, "fee_variant", None)
    if fv is not None:
        cat = getattr(fv, "category", None)
        if cat is not None:
            return cat.name, cat.priority, entitlements.read(cat)
    return "", 100, []


def _status_after(fee: EnrollmentFee, paid_after: Decimal) -> str:
    """Calcule le statut prévu après allocation hypothétique."""
    if fee.status == EnrollmentFeeStatus.WAIVED.value:
        return EnrollmentFeeStatus.WAIVED.value
    if paid_after >= fee.amount:
        return EnrollmentFeeStatus.PAID.value
    if paid_after > 0:
        return EnrollmentFeeStatus.PARTIAL.value
    return EnrollmentFeeStatus.PENDING.value


async def preview_allocation(
    db: AsyncSession, enrollment_id: int, amount: Decimal
) -> AllocationPreviewResponse:
    """Montre comment `amount` serait alloué sans rien écrire.

    Inclut le surplus et la raison de rejet (décision Marcel #2 : reject
    par défaut en P0).
    """
    if amount <= 0:
        raise BusinessValidationError("amount must be positive")

    fees = await repo.get_enrollment_fees_ordered_by_priority(db, enrollment_id)
    if not fees:
        return AllocationPreviewResponse(
            enrollment_id=enrollment_id,
            amount=amount,
            total_remaining_before=Decimal("0"),
            total_remaining_after=Decimal("0"),
            surplus=amount,
            can_record=False,
            reject_reason="Aucun frais configuré pour cette inscription",
            lines=[],
        )

    # Une requete groupee pour toute l'inscription, pas une par frais : un
    # apercu sur six frais coutait six allers-retours a la base pendant que
    # le caissier attendait devant la famille.
    deja_verse = await fees_paid.paid_by_enrollment(db, enrollment_id)
    fees_with_paid: list[tuple[EnrollmentFee, Decimal]] = [
        (fee, deja_verse.get(fee.id, Decimal("0"))) for fee in fees
    ]

    total_remaining_before = sum(
        (
            f.amount - paid
            for f, paid in fees_with_paid
            if f.status != EnrollmentFeeStatus.WAIVED.value
        ),
        Decimal("0"),
    )
    total_remaining_before = max(total_remaining_before, Decimal("0"))

    plannable = [
        (f, paid)
        for f, paid in fees_with_paid
        if f.status in (EnrollmentFeeStatus.PENDING.value, EnrollmentFeeStatus.PARTIAL.value)
        and (f.amount - paid) > 0
    ]
    splits, surplus = plan_allocation(amount, plannable)
    split_map = {fee.id: allocated for fee, allocated in splits}

    lines: list[AllocationPreviewLine] = []
    for fee, paid in fees_with_paid:
        allocated = split_map.get(fee.id, Decimal("0"))
        paid_after = paid + allocated
        cat_name, cat_priority, cat_entitlements = _resolve_category(fee)
        lines.append(
            AllocationPreviewLine(
                enrollment_fee_id=fee.id,
                fee_category_name=cat_name,
                fee_category_entitlements=cat_entitlements,
                fee_category_priority=cat_priority,
                fee_total=fee.amount,
                fee_paid_before=paid,
                allocated=allocated,
                fee_paid_after=paid_after,
                status_after=_status_after(fee, paid_after),
            )
        )

    can_record = surplus <= 0
    reject_reason = None
    if not can_record:
        reject_reason = (
            f"Montant versé ({amount}) supérieur à la dette restante "
            f"({total_remaining_before}). Surplus : {surplus}."
        )

    return AllocationPreviewResponse(
        enrollment_id=enrollment_id,
        amount=amount,
        total_remaining_before=total_remaining_before,
        total_remaining_after=max(total_remaining_before - amount, Decimal("0")),
        surplus=max(surplus, Decimal("0")),
        can_record=can_record,
        reject_reason=reject_reason,
        lines=lines,
    )
