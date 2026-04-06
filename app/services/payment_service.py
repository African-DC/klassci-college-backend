"""Service paiements — logique métier CRUD + mise à jour auto du statut EnrollmentFee."""

import logging
from datetime import datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditAction, audit_log
from app.core.exceptions import BusinessValidationError, NotFoundError
from app.models.fee import EnrollmentFeeStatus, PaymentStatus
from app.repositories import payment_repository as repo
from app.schemas.payment import PaymentCreate, PaymentListResponse, PaymentResponse

logger = logging.getLogger(__name__)


def _to_response(payment: object) -> PaymentResponse:
    """Convertit un Payment ORM en PaymentResponse."""
    return PaymentResponse.model_validate(payment)


async def create_payment(
    db: AsyncSession,
    data: PaymentCreate,
    *,
    received_by: int,
) -> PaymentResponse:
    """Crée un paiement et met à jour le statut EnrollmentFee automatiquement.

    1. Vérifie que l'EnrollmentFee existe et n'est pas waived/paid
    2. Vérifie que le montant ne dépasse pas le solde restant
    3. Crée le Payment (status=completed pour cash, pending sinon)
    4. Recalcule le total payé et met à jour EnrollmentFee.status
    """
    # Tout dans une transaction avec FOR UPDATE pour éviter les race conditions
    async with db.begin_nested():
        enrollment_fee = await repo.get_enrollment_fee_for_update(db, data.enrollment_fee_id)
        if enrollment_fee is None:
            raise NotFoundError("EnrollmentFee", data.enrollment_fee_id)

        if enrollment_fee.status in (
            EnrollmentFeeStatus.WAIVED.value,
            EnrollmentFeeStatus.PAID.value,
        ):
            raise BusinessValidationError(
                f"Cannot add payment: enrollment fee status is '{enrollment_fee.status}'"
            )

        # Calculer le solde restant
        total_paid = await repo.get_total_paid_for_enrollment_fee(db, data.enrollment_fee_id)
        remaining = enrollment_fee.amount - total_paid
        if data.amount > remaining:
            raise BusinessValidationError(
                f"Payment amount {data.amount} exceeds remaining balance {remaining}"
            )

        # Déterminer le statut initial du paiement
        initial_status = PaymentStatus.COMPLETED.value

        payment = await repo.create_payment(
            db,
            enrollment_fee_id=data.enrollment_fee_id,
            amount=data.amount,
            method=data.method,
            status=initial_status,
            reference=data.reference,
            received_by=received_by,
            notes=data.notes,
        )

        # Recalculer le total payé et mettre à jour le statut EnrollmentFee
        new_total_paid = total_paid + data.amount
        if new_total_paid >= enrollment_fee.amount:
            enrollment_fee.status = EnrollmentFeeStatus.PAID.value
        elif new_total_paid > Decimal("0"):
            enrollment_fee.status = EnrollmentFeeStatus.PARTIAL.value
        else:
            enrollment_fee.status = EnrollmentFeeStatus.PENDING.value
        await db.flush()

        await audit_log(
            db,
            entity_type="payment",
            action=AuditAction.CREATE,
            user_id=received_by,
            entity_id=payment.id,
            new_values={
                "enrollment_fee_id": data.enrollment_fee_id,
                "amount": str(data.amount),
                "method": data.method,
                "reference": data.reference,
                "enrollment_fee_status": enrollment_fee.status,
            },
        )

    await db.commit()

    refreshed = await repo.get_payment_by_id(db, payment.id)
    if refreshed is None:
        raise NotFoundError("Payment", payment.id)
    return _to_response(refreshed)


async def list_payments(
    db: AsyncSession,
    *,
    status: str | None = None,
    method: str | None = None,
    enrollment_fee_id: int | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    page: int = 1,
    size: int = 20,
) -> PaymentListResponse:
    """Retourne une page de paiements."""
    payments, total = await repo.list_payments(
        db,
        status=status,
        method=method,
        enrollment_fee_id=enrollment_fee_id,
        date_from=date_from,
        date_to=date_to,
        page=page,
        size=size,
    )
    return PaymentListResponse(
        items=[_to_response(p) for p in payments],
        total=total,
        page=page,
        size=size,
    )


async def get_payment(db: AsyncSession, payment_id: int) -> PaymentResponse:
    """Retourne un paiement par ID ou lève 404."""
    payment = await repo.get_payment_by_id(db, payment_id)
    if payment is None:
        raise NotFoundError("Payment", payment_id)
    return _to_response(payment)


async def get_student_payments(db: AsyncSession, enrollment_id: int) -> list[PaymentResponse]:
    """Retourne tous les paiements liés à une inscription."""
    payments = await repo.get_payments_by_enrollment_id(db, enrollment_id)
    return [_to_response(p) for p in payments]
