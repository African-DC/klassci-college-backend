"""Repository paiements — accès DB pour Payment et EnrollmentFee."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.fee import EnrollmentFee, Payment, PaymentStatus


async def get_payment_by_id(db: AsyncSession, payment_id: int) -> Payment | None:
    """Retourne un paiement par ID avec sa relation enrollment_fee chargée."""
    stmt = (
        select(Payment)
        .where(Payment.id == payment_id)
        .options(selectinload(Payment.enrollment_fee))
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


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
) -> tuple[list[Payment], int]:
    """Retourne une page de paiements avec le total."""
    base = select(Payment).options(selectinload(Payment.enrollment_fee))

    if status is not None:
        base = base.where(Payment.status == status)
    if method is not None:
        base = base.where(Payment.method == method)
    if enrollment_fee_id is not None:
        base = base.where(Payment.enrollment_fee_id == enrollment_fee_id)
    if date_from is not None:
        base = base.where(Payment.created_at >= date_from)
    if date_to is not None:
        base = base.where(Payment.created_at <= date_to)

    count_stmt = select(func.count()).select_from(base.subquery())
    total: int = (await db.execute(count_stmt)).scalar() or 0

    stmt = base.offset((page - 1) * size).limit(size).order_by(Payment.id.desc())
    rows = (await db.execute(stmt)).scalars().all()
    return list(rows), total


async def get_enrollment_fee_by_id(
    db: AsyncSession, enrollment_fee_id: int
) -> EnrollmentFee | None:
    """Retourne un EnrollmentFee par ID."""
    stmt = select(EnrollmentFee).where(EnrollmentFee.id == enrollment_fee_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_enrollment_fee_for_update(
    db: AsyncSession, enrollment_fee_id: int
) -> EnrollmentFee | None:
    """Retourne un EnrollmentFee avec verrou FOR UPDATE (race condition guard)."""
    stmt = select(EnrollmentFee).where(EnrollmentFee.id == enrollment_fee_id).with_for_update()
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_total_paid_for_enrollment_fee(db: AsyncSession, enrollment_fee_id: int) -> Decimal:
    """Calcule le total des paiements complétés pour un EnrollmentFee."""
    stmt = select(func.coalesce(func.sum(Payment.amount), 0)).where(
        Payment.enrollment_fee_id == enrollment_fee_id,
        Payment.status == PaymentStatus.COMPLETED.value,
    )
    result = await db.execute(stmt)
    return Decimal(str(result.scalar()))


async def create_payment(
    db: AsyncSession,
    *,
    enrollment_fee_id: int,
    amount: Decimal,
    method: str,
    status: str,
    reference: str | None,
    received_by: int | None,
    notes: str | None,
) -> Payment:
    """Crée un paiement et le flush pour obtenir l'ID."""
    payment = Payment(
        enrollment_fee_id=enrollment_fee_id,
        amount=amount,
        method=method,
        status=status,
        reference=reference,
        received_by=received_by,
        notes=notes,
    )
    db.add(payment)
    await db.flush()
    return payment


async def get_payments_by_enrollment_id(db: AsyncSession, enrollment_id: int) -> list[Payment]:
    """Retourne tous les paiements liés à une inscription (via enrollment_fees)."""
    stmt = (
        select(Payment)
        .join(EnrollmentFee, Payment.enrollment_fee_id == EnrollmentFee.id)
        .where(EnrollmentFee.enrollment_id == enrollment_id)
        .options(selectinload(Payment.enrollment_fee))
        .order_by(Payment.id.desc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())
