"""Remises sur frais : le net est facturé, le nominal et la décision sont conservés.

Une transaction et un verrou sur la ligne de frais protègent à la fois la caisse,
la remise et l'annulation. Les versements ne sont jamais modifiés. Une réduction
qui créerait un trop-perçu, même avec un versement en attente, est refusée.
"""

from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditAction, audit_log
from app.core.exceptions import BusinessValidationError, NotFoundError
from app.models.enrollment import CLOSED_STATUSES, Enrollment
from app.models.fee import (
    EnrollmentFee,
    EnrollmentFeeStatus,
    Payment,
    PaymentAllocation,
    PaymentStatus,
)
from app.models.fee_discount import EnrollmentFeeDiscount
from app.schemas.fee_discount import FeeDiscountResponse, FeeDiscountUpsert
from app.services import fees_paid
from app.services.payments._allocation import recompute_fee_status

CENT = Decimal("0.01")
LIVE_STATUSES = (PaymentStatus.PENDING.value, PaymentStatus.COMPLETED.value)


def compute_discount(original: Decimal, data: FeeDiscountUpsert) -> Decimal:
    """Calcul sans flottant ; aucune remise négative ou supérieure à la dette."""
    if original <= 0:
        raise BusinessValidationError("Ce frais n'a pas de montant positif à réduire.")
    if data.kind == "percent":
        if data.value > 100:
            raise BusinessValidationError("Le pourcentage ne peut pas dépasser 100 %.")
        discount = (original * data.value / Decimal("100")).quantize(
            CENT, rounding=ROUND_HALF_UP
        )
    else:
        discount = data.value.quantize(CENT)
    if discount <= 0 or discount > original:
        raise BusinessValidationError(
            "La réduction doit être positive et ne peut dépasser le montant initial."
        )
    return discount


async def _ensure_enrollment(
    db: AsyncSession, enrollment_id: int, *, writing: bool
) -> None:
    enrollment = (
        await db.execute(select(Enrollment).where(Enrollment.id == enrollment_id))
    ).scalar_one_or_none()
    if enrollment is None:
        raise NotFoundError("Enrollment", enrollment_id)
    if writing and enrollment.status in CLOSED_STATUSES:
        raise BusinessValidationError(
            "Une inscription fermée ne peut recevoir de réduction."
        )


async def _locked_fee(
    db: AsyncSession, enrollment_id: int, fee_id: int
) -> EnrollmentFee:
    # Verrou identique au guichet : la ligne et ses versements restent cohérents.
    fee = (
        await db.execute(
            select(EnrollmentFee)
            .where(
                EnrollmentFee.id == fee_id,
                EnrollmentFee.enrollment_id == enrollment_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if fee is None:
        raise NotFoundError("EnrollmentFee", fee_id)
    return fee


async def _live_allocated(db: AsyncSession, fee_id: int) -> Decimal:
    stmt = (
        select(func.coalesce(func.sum(PaymentAllocation.amount), 0))
        .select_from(PaymentAllocation)
        .join(Payment, Payment.id == PaymentAllocation.payment_id)
        .where(
            PaymentAllocation.enrollment_fee_id == fee_id,
            Payment.status.in_(LIVE_STATUSES),
        )
    )
    return Decimal(str((await db.execute(stmt)).scalar_one()))


def _response(discount: EnrollmentFeeDiscount, due: Decimal) -> FeeDiscountResponse:
    return FeeDiscountResponse(
        enrollment_fee_id=discount.enrollment_fee_id,
        original_amount=discount.original_amount,
        discount_amount=discount.discount_amount,
        amount_due=due,
        kind=discount.kind,
        value=discount.value,
        reason=discount.reason,
        granted_by=discount.granted_by,
        created_at=discount.created_at,
        updated_at=discount.updated_at,
    )


async def list_discounts(
    db: AsyncSession, enrollment_id: int
) -> list[FeeDiscountResponse]:
    await _ensure_enrollment(db, enrollment_id, writing=False)
    rows = (
        await db.execute(
            select(EnrollmentFeeDiscount, EnrollmentFee.amount)
            .join(
                EnrollmentFee, EnrollmentFee.id == EnrollmentFeeDiscount.enrollment_fee_id
            )
            .where(EnrollmentFee.enrollment_id == enrollment_id)
            .order_by(EnrollmentFee.id)
        )
    ).all()
    return [_response(discount, due) for discount, due in rows]


async def set_discount(
    db: AsyncSession,
    enrollment_id: int,
    fee_id: int,
    data: FeeDiscountUpsert,
    *,
    actor: int,
) -> FeeDiscountResponse:
    await _ensure_enrollment(db, enrollment_id, writing=True)
    async with db.begin_nested():
        fee = await _locked_fee(db, enrollment_id, fee_id)
        existing = (
            await db.execute(
                select(EnrollmentFeeDiscount)
                .where(EnrollmentFeeDiscount.enrollment_fee_id == fee.id)
            )
        ).scalar_one_or_none()
        if (
            fee.status in (EnrollmentFeeStatus.WAIVED, EnrollmentFeeStatus.IN_KIND)
            and not existing
        ):
            raise BusinessValidationError(
                "Ce frais est déjà exonéré ou déposé en nature : aucune remise ne peut y être posée."
            )

        nominal = Decimal(str(existing.original_amount if existing else fee.amount))
        reduction = compute_discount(nominal, data)
        net = nominal - reduction
        reserved = await _live_allocated(db, fee.id)
        if net < reserved:
            raise BusinessValidationError(
                f"Réduction refusée : {reserved} FCFA sont déjà encaissés ou en attente "
                f"sur ce frais. Le montant réduit ({net} FCFA) ne peut leur être inférieur."
            )

        old = (
            {"amount_due": str(fee.amount), "discount": str(existing.discount_amount)}
            if existing
            else {"amount_due": str(fee.amount), "discount": None}
        )
        if existing is None:
            existing = EnrollmentFeeDiscount(
                enrollment_fee_id=fee.id,
                original_amount=nominal,
                granted_by=actor,
            )
            db.add(existing)
        existing.kind = data.kind
        existing.value = data.value
        existing.discount_amount = reduction
        existing.reason = data.reason
        existing.granted_by = actor
        fee.amount = net
        if net == 0:
            fee.status = EnrollmentFeeStatus.WAIVED.value
        else:
            # Le statut waived précédent pouvait provenir d'une remise totale.
            fee.status = EnrollmentFeeStatus.PENDING.value
            paid = (await fees_paid.paid_by_enrollment(db, enrollment_id)).get(
                fee.id, Decimal("0")
            )
            recompute_fee_status(fee, paid)
        await db.flush()
        await db.refresh(existing)
        await audit_log(
            db,
            entity_type="enrollment_fee",
            action=AuditAction.UPDATE,
            entity_id=fee.id,
            user_id=actor,
            old_values=old,
            new_values={
                "action": "set_discount",
                "nominal": str(nominal),
                "discount": str(reduction),
                "amount_due": str(net),
                "kind": data.kind,
                "value": str(data.value),
                "reason": data.reason,
                "enrollment_id": enrollment_id,
            },
        )
        result = _response(existing, net)
    await db.commit()
    return result


async def remove_discount(
    db: AsyncSession, enrollment_id: int, fee_id: int, *, actor: int
) -> None:
    await _ensure_enrollment(db, enrollment_id, writing=True)
    async with db.begin_nested():
        fee = await _locked_fee(db, enrollment_id, fee_id)
        discount = (
            await db.execute(
                select(EnrollmentFeeDiscount)
                .where(EnrollmentFeeDiscount.enrollment_fee_id == fee.id)
            )
        ).scalar_one_or_none()
        if discount is None:
            raise NotFoundError("EnrollmentFeeDiscount", fee_id)
        previous = {
            "discount": str(discount.discount_amount),
            "amount_due": str(fee.amount),
            "nominal": str(discount.original_amount),
            "reason": discount.reason,
        }
        fee.amount = discount.original_amount
        fee.status = EnrollmentFeeStatus.PENDING.value
        paid = (await fees_paid.paid_by_enrollment(db, enrollment_id)).get(
            fee.id, Decimal("0")
        )
        recompute_fee_status(fee, paid)
        await db.delete(discount)
        await db.flush()
        await audit_log(
            db,
            entity_type="enrollment_fee",
            action=AuditAction.UPDATE,
            entity_id=fee.id,
            user_id=actor,
            old_values=previous,
            new_values={
                "action": "remove_discount",
                "enrollment_id": enrollment_id,
                "amount_due": str(fee.amount),
            },
        )
    await db.commit()
