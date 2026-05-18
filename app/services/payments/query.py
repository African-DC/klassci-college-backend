"""Read-only queries paiements : list, get, get_by_enrollment, summary."""

from datetime import datetime

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.enrollment import Enrollment
from app.models.fee import EnrollmentFee, Payment, PaymentStatus
from app.repositories import payment_repository as repo
from app.schemas.payment import (
    PaymentListResponse,
    PaymentResponse,
    PaymentSummaryResponse,
)
from app.services.payments._response import payment_to_response


async def list_payments(
    db: AsyncSession,
    *,
    status: str | None = None,
    method: str | None = None,
    enrollment_fee_id: int | None = None,
    enrollment_id: int | None = None,
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
        enrollment_id=enrollment_id,
        date_from=date_from,
        date_to=date_to,
        page=page,
        size=size,
    )
    return PaymentListResponse(
        items=[payment_to_response(p) for p in payments],
        total=total,
        page=page,
        size=size,
    )


async def get_payment(db: AsyncSession, payment_id: int) -> PaymentResponse:
    """Retourne un paiement par ID ou lève 404."""
    payment = await repo.get_payment_with_allocations(db, payment_id)
    if payment is None:
        raise NotFoundError("Payment", payment_id)
    return payment_to_response(payment)


async def get_student_payments(
    db: AsyncSession, enrollment_id: int
) -> list[PaymentResponse]:
    """Retourne tous les paiements liés à une inscription."""
    payments = await repo.get_payments_by_enrollment_id(db, enrollment_id)
    return [payment_to_response(p) for p in payments]


async def get_payments_summary(
    db: AsyncSession,
    *,
    academic_year_id: int | None = None,
) -> PaymentSummaryResponse:
    """Agrège les statistiques de paiement (KPIs dashboard admin)."""
    expected_stmt = select(
        func.coalesce(func.sum(EnrollmentFee.amount), 0).label("expected"),
    )
    if academic_year_id is not None:
        expected_stmt = expected_stmt.join(
            Enrollment, EnrollmentFee.enrollment_id == Enrollment.id
        ).where(Enrollment.academic_year_id == academic_year_id)

    expected_row = (await db.execute(expected_stmt)).one()
    total_expected = float(expected_row.expected)

    pay_stmt = select(
        func.count().label("payment_count"),
        func.coalesce(
            func.sum(
                case(
                    (Payment.status == PaymentStatus.COMPLETED.value, Payment.amount),
                    else_=0,
                )
            ),
            0,
        ).label("total_paid"),
        func.coalesce(
            func.sum(
                case(
                    (Payment.status == PaymentStatus.PENDING.value, Payment.amount),
                    else_=0,
                )
            ),
            0,
        ).label("total_pending"),
        func.coalesce(
            func.sum(
                case(
                    (Payment.status == PaymentStatus.CANCELLED.value, Payment.amount),
                    else_=0,
                )
            ),
            0,
        ).label("total_cancelled"),
    )
    if academic_year_id is not None:
        pay_stmt = pay_stmt.join(
            Enrollment, Payment.enrollment_id == Enrollment.id
        ).where(Enrollment.academic_year_id == academic_year_id)

    pay_row = (await db.execute(pay_stmt)).one()

    total_paid = float(pay_row.total_paid)
    total_pending = float(pay_row.total_pending)
    total_cancelled = float(pay_row.total_cancelled)
    payment_count = pay_row.payment_count
    completion_rate = (
        round(total_paid / total_expected * 100, 1) if total_expected > 0 else 0.0
    )

    return PaymentSummaryResponse(
        total_expected=total_expected,
        total_paid=total_paid,
        total_pending=total_pending,
        total_cancelled=total_cancelled,
        payment_count=payment_count,
        completion_rate=completion_rate,
    )
