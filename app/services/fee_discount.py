"""Réduction ciblée d'une ligne de frais, jamais d'un tarif collectif.

V1 volontairement conservatrice : les lignes avec allocations (y compris
annulées pour préserver la traçabilité) sont immuables. Un avoir après
encaissement exige un workflow distinct, pas une réécriture de la facture.
"""
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditAction, audit_log
from app.core.exceptions import BusinessValidationError, NotFoundError
from app.models.enrollment import Enrollment, is_closed
from app.models.fee import EnrollmentFee, EnrollmentFeeStatus, FeeCategory
from app.schemas.fee_discount import DiscountInput, DiscountLine
from app.services.fees_paid import fee_ids_with_allocations

CENT = Decimal("0.01")

async def _load_enrollment(db: AsyncSession, enrollment_id: int, *, lock: bool = False):
    stmt = select(Enrollment).where(Enrollment.id == enrollment_id)
    if lock:
        stmt = stmt.with_for_update()
    enrollment = (await db.execute(stmt)).scalar_one_or_none()
    if enrollment is None:
        raise NotFoundError("Enrollment", enrollment_id)
    return enrollment

async def list_discounts(db: AsyncSession, enrollment_id: int) -> list[DiscountLine]:
    await _load_enrollment(db, enrollment_id)
    stmt = (
        select(EnrollmentFee, FeeCategory.name)
        .join(FeeCategory, FeeCategory.id == EnrollmentFee.fee_category_id)
        .where(EnrollmentFee.enrollment_id == enrollment_id)
        .order_by(EnrollmentFee.id)
    )
    result = (await db.execute(stmt)).all()
    return [_line(fee, name) for fee, name in result]

def _line(fee: EnrollmentFee, category_name: str) -> DiscountLine:
    gross = fee.original_amount if fee.original_amount is not None else fee.amount
    return DiscountLine(
        fee_id=fee.id,
        category_name=category_name,
        original_amount=gross,
        payable_amount=fee.amount,
        discount_kind=fee.discount_kind,
        discount_value=fee.discount_value,
        discount_amount=max(Decimal("0"), gross - fee.amount),
        discount_reason=fee.discount_reason,
    )

async def set_discount(
    db: AsyncSession, enrollment_id: int, fee_id: int,
    payload: DiscountInput | None, *, actor: int
) -> DiscountLine:
    # Lock the enrollment first: serializes same-student discounts while
    # a payment can be occurring. Allocation check is deliberately in txn.
    enrollment = await _load_enrollment(db, enrollment_id, lock=True)
    if is_closed(enrollment.status) or enrollment.archived_at is not None:
        raise BusinessValidationError("Une inscription fermée ne peut pas être modifiée.")
    stmt = (
        select(EnrollmentFee, FeeCategory.name)
        .join(FeeCategory, FeeCategory.id == EnrollmentFee.fee_category_id)
        .where(EnrollmentFee.id == fee_id, EnrollmentFee.enrollment_id == enrollment_id)
        .with_for_update()
    )
    row = (await db.execute(stmt)).first()
    if row is None:
        raise NotFoundError("EnrollmentFee", fee_id)
    fee, category_name = row
    if fee.status in (EnrollmentFeeStatus.WAIVED, EnrollmentFeeStatus.IN_KIND):
        raise BusinessValidationError("Frais déjà exonéré ou déposé en nature.")
    if fee.id in await fee_ids_with_allocations(db, enrollment_id):
        raise BusinessValidationError(
            "Un versement a déjà été imputé à ce frais. "
            "La correction exige un traitement comptable distinct."
        )
    before = _line(fee, category_name)
    gross = before.original_amount
    if payload is None:
        fee.amount = gross
        fee.original_amount = None
        fee.discount_kind = None
        fee.discount_value = None
        fee.discount_reason = None
    else:
        reduction = (
            payload.value if payload.kind == "fixed"
            else gross * payload.value / Decimal("100")
        ).quantize(CENT, rounding=ROUND_HALF_UP)
        if reduction > gross:
            raise BusinessValidationError("La remise dépasse le montant de ce frais.")
        fee.original_amount = gross
        fee.amount = gross - reduction
        fee.discount_kind = payload.kind
        fee.discount_value = payload.value
        fee.discount_reason = payload.reason
    await db.flush()
    after = _line(fee, category_name)
    await audit_log(
        db, entity_type="enrollment_fee", entity_id=fee.id,
        action=AuditAction.UPDATE, user_id=actor,
        old_values={"discount": before.model_dump(mode="json")},
        new_values={"discount": after.model_dump(mode="json")},
    )
    await db.commit()
    return after
