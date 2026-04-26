"""Service paiements — logique métier CRUD + mise à jour auto du statut EnrollmentFee."""

import logging
from datetime import datetime
from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.audit import AuditAction, audit_log
from app.core.exceptions import BusinessValidationError, NotFoundError
from app.models.academic import SchoolSettings
from app.models.enrollment import Enrollment
from app.models.fee import (
    EnrollmentFee,
    EnrollmentFeeStatus,
    FeeVariant,
    Payment,
    PaymentStatus,
)
from app.models.user import User
from app.repositories import payment_repository as repo
from app.schemas.payment import (
    PaymentCreate,
    PaymentListResponse,
    PaymentResponse,
    PaymentSummaryResponse,
)
from app.services.pdf_service import generate_receipt_pdf

# ---------------------------------------------------------------------------
# State machine for payment transitions
# ---------------------------------------------------------------------------

VALID_TRANSITIONS: dict[str, list[str]] = {
    "pending": ["completed", "cancelled"],
    "completed": ["refunded"],
    "failed": [],
    "refunded": [],
    "cancelled": [],
}

logger = logging.getLogger(__name__)


def _to_response(payment: Payment) -> PaymentResponse:
    """Convertit un Payment ORM en PaymentResponse avec champs enrichis."""
    student_name = None
    student_photo_url = None
    fee_name = None

    ef = getattr(payment, "enrollment_fee", None)
    if ef is not None:
        enrollment = getattr(ef, "enrollment", None)
        if enrollment is not None:
            student = getattr(enrollment, "student", None)
            if student is not None:
                student_name = f"{student.first_name} {student.last_name}"
                student_photo_url = getattr(student, "photo_url", None)
        fv = getattr(ef, "fee_variant", None)
        if fv is not None:
            cat = getattr(fv, "category", None)
            if cat is not None:
                fee_name = cat.name

    return PaymentResponse(
        id=payment.id,
        enrollment_fee_id=payment.enrollment_fee_id,
        amount=payment.amount,
        method=payment.method,
        status=payment.status,
        reference=payment.reference,
        received_by=payment.received_by,
        notes=payment.notes,
        created_at=payment.created_at,
        updated_at=payment.updated_at,
        student_name=student_name,
        student_photo_url=student_photo_url,
        fee_name=fee_name,
    )


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

    # After commit, notify student of payment received (best-effort)
    try:
        from app.models.notification import NotificationType
        from app.services import notification_dispatch_service as notif

        if refreshed and refreshed.enrollment_fee and refreshed.enrollment_fee.enrollment:
            enrollment = refreshed.enrollment_fee.enrollment
            if enrollment.student and enrollment.student.user_id:
                await notif.dispatch_notification(
                    db,
                    user_id=enrollment.student.user_id,
                    notification_type=NotificationType.PAYMENT_RECEIVED,
                    context={
                        "title": "Paiement reçu",
                        "body": f"Votre paiement de {data.amount} FCFA a été enregistré.",
                        "amount": str(data.amount),
                    },
                )
    except Exception:
        logger.exception("Failed to dispatch payment notification")

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


# ---------------------------------------------------------------------------
# Receipt PDF
# ---------------------------------------------------------------------------


async def _get_school_settings(db: AsyncSession) -> dict:
    """Fetch the singleton SchoolSettings row."""
    stmt = select(SchoolSettings).limit(1)
    result = await db.execute(stmt)
    settings = result.scalar_one_or_none()
    if settings is None:
        return {"school_name": "Etablissement", "ministry_code": None}
    return {
        "school_name": settings.school_name,
        "ministry_code": settings.ministry_code,
        "address": settings.address,
        "phone": settings.phone,
    }


async def get_payment_receipt_pdf(db: AsyncSession, payment_id: int) -> bytes:
    """Generate and return a PDF receipt for a payment."""
    # Load payment with full chain: payment -> enrollment_fee -> fee_variant -> category
    # and enrollment_fee -> enrollment -> student
    stmt = (
        select(Payment)
        .where(Payment.id == payment_id)
        .options(
            selectinload(Payment.enrollment_fee)
            .selectinload(EnrollmentFee.fee_variant)
            .selectinload(FeeVariant.category),
            selectinload(Payment.enrollment_fee)
            .selectinload(EnrollmentFee.enrollment)
            .selectinload(Enrollment.student),
        )
    )
    result = await db.execute(stmt)
    payment = result.scalar_one_or_none()
    if payment is None:
        raise NotFoundError("Payment", payment_id)

    # Student name
    student_name = ""
    enrollment_fee = payment.enrollment_fee
    if enrollment_fee and enrollment_fee.enrollment and enrollment_fee.enrollment.student:
        s = enrollment_fee.enrollment.student
        student_name = f"{s.first_name} {s.last_name}"

    # Fee description
    fee_description = ""
    if enrollment_fee and enrollment_fee.fee_variant and enrollment_fee.fee_variant.category:
        fee_description = enrollment_fee.fee_variant.category.name

    # Received by name — User model has email only (no first/last name)
    received_by_name = ""
    if payment.received_by:
        user_stmt = select(User).where(User.id == payment.received_by)
        user_result = await db.execute(user_stmt)
        user = user_result.scalar_one_or_none()
        if user:
            received_by_name = user.email.split("@")[0]

    school = await _get_school_settings(db)

    payment_data = {
        "payment_id": payment.id,
        "amount": payment.amount,
        "method": payment.method,
        "reference": payment.reference,
        "status": payment.status,
        "notes": payment.notes,
        "student_name": student_name,
        "fee_description": fee_description,
        "created_at": payment.created_at,
        "received_by_name": received_by_name,
    }

    return generate_receipt_pdf(payment_data, school)


# ---------------------------------------------------------------------------
# Validate / Cancel / Summary
# ---------------------------------------------------------------------------


async def validate_payment(
    db: AsyncSession,
    payment_id: int,
    *,
    validated_by: int,
) -> PaymentResponse:
    """Transition un paiement de pending à completed."""
    from fastapi import HTTPException

    async with db.begin_nested():
        # Lock payment row
        stmt = select(Payment).where(Payment.id == payment_id).with_for_update()
        result = await db.execute(stmt)
        payment = result.scalar_one_or_none()
        if payment is None:
            raise NotFoundError("Payment", payment_id)

        current = payment.status
        if "completed" not in VALID_TRANSITIONS.get(current, []):
            raise HTTPException(
                status_code=409,
                detail=f"Transition invalide : impossible de passer de '{current}' à 'completed'",
            )

        payment.status = PaymentStatus.COMPLETED.value
        await db.flush()

        # Recalculate enrollment fee status
        enrollment_fee = await repo.get_enrollment_fee_for_update(db, payment.enrollment_fee_id)
        if enrollment_fee is not None:
            total_paid = await repo.get_total_paid_for_enrollment_fee(db, payment.enrollment_fee_id)
            if total_paid >= enrollment_fee.amount:
                enrollment_fee.status = EnrollmentFeeStatus.PAID.value
            elif total_paid > Decimal("0"):
                enrollment_fee.status = EnrollmentFeeStatus.PARTIAL.value
            else:
                enrollment_fee.status = EnrollmentFeeStatus.PENDING.value
            await db.flush()

        await audit_log(
            db,
            entity_type="payment",
            action=AuditAction.UPDATE,
            user_id=validated_by,
            entity_id=payment.id,
            old_values={"status": current},
            new_values={"status": payment.status},
        )

    await db.commit()

    # Notification best-effort
    try:
        from app.models.notification import NotificationType
        from app.services import notification_dispatch_service as notif

        refreshed = await repo.get_payment_by_id(db, payment.id)
        if refreshed and refreshed.enrollment_fee and refreshed.enrollment_fee.enrollment:
            enrollment = refreshed.enrollment_fee.enrollment
            if enrollment.student and enrollment.student.user_id:
                await notif.dispatch_notification(
                    db,
                    user_id=enrollment.student.user_id,
                    notification_type=NotificationType.PAYMENT_RECEIVED,
                    context={
                        "title": "Paiement validé",
                        "body": f"Votre paiement de {payment.amount} FCFA a été validé.",
                        "amount": str(payment.amount),
                    },
                )
    except Exception:
        logger.exception("Failed to dispatch payment validation notification")

    refreshed = await repo.get_payment_by_id(db, payment.id)
    if refreshed is None:
        raise NotFoundError("Payment", payment.id)
    return _to_response(refreshed)


async def cancel_payment(
    db: AsyncSession,
    payment_id: int,
    *,
    cancelled_by: int,
) -> PaymentResponse:
    """Transition un paiement de pending à cancelled."""
    from fastapi import HTTPException

    async with db.begin_nested():
        stmt = select(Payment).where(Payment.id == payment_id).with_for_update()
        result = await db.execute(stmt)
        payment = result.scalar_one_or_none()
        if payment is None:
            raise NotFoundError("Payment", payment_id)

        current = payment.status
        if "cancelled" not in VALID_TRANSITIONS.get(current, []):
            raise HTTPException(
                status_code=409,
                detail=f"Transition invalide : impossible de passer de '{current}' à 'cancelled'",
            )

        payment.status = PaymentStatus.CANCELLED.value
        await db.flush()

        await audit_log(
            db,
            entity_type="payment",
            action=AuditAction.UPDATE,
            user_id=cancelled_by,
            entity_id=payment.id,
            old_values={"status": current},
            new_values={"status": payment.status},
        )

    await db.commit()

    refreshed = await repo.get_payment_by_id(db, payment.id)
    if refreshed is None:
        raise NotFoundError("Payment", payment.id)
    return _to_response(refreshed)


async def get_payments_summary(
    db: AsyncSession,
    *,
    academic_year_id: int | None = None,
) -> PaymentSummaryResponse:
    """Agrège les statistiques de paiement."""
    from app.models.enrollment import Enrollment

    # Total expected (sum of enrollment_fees amounts)
    expected_stmt = select(
        func.coalesce(func.sum(EnrollmentFee.amount), 0).label("expected"),
    )
    if academic_year_id is not None:
        expected_stmt = expected_stmt.join(
            Enrollment, EnrollmentFee.enrollment_id == Enrollment.id
        ).where(Enrollment.academic_year_id == academic_year_id)

    expected_row = (await db.execute(expected_stmt)).one()
    total_expected = float(expected_row.expected)

    # Payment aggregates
    pay_stmt = select(
        func.count().label("payment_count"),
        func.coalesce(
            func.sum(
                case((Payment.status == PaymentStatus.COMPLETED.value, Payment.amount), else_=0)
            ),
            0,
        ).label("total_paid"),
        func.coalesce(
            func.sum(
                case((Payment.status == PaymentStatus.PENDING.value, Payment.amount), else_=0)
            ),
            0,
        ).label("total_pending"),
        func.coalesce(
            func.sum(
                case((Payment.status == PaymentStatus.CANCELLED.value, Payment.amount), else_=0)
            ),
            0,
        ).label("total_cancelled"),
    )
    if academic_year_id is not None:
        pay_stmt = (
            pay_stmt.join(EnrollmentFee, Payment.enrollment_fee_id == EnrollmentFee.id)
            .join(Enrollment, EnrollmentFee.enrollment_id == Enrollment.id)
            .where(Enrollment.academic_year_id == academic_year_id)
        )

    pay_row = (await db.execute(pay_stmt)).one()

    total_paid = float(pay_row.total_paid)
    total_pending = float(pay_row.total_pending)
    total_cancelled = float(pay_row.total_cancelled)
    payment_count = pay_row.payment_count
    completion_rate = round(total_paid / total_expected * 100, 1) if total_expected > 0 else 0.0

    return PaymentSummaryResponse(
        total_expected=total_expected,
        total_paid=total_paid,
        total_pending=total_pending,
        total_cancelled=total_cancelled,
        payment_count=payment_count,
        completion_rate=completion_rate,
    )
