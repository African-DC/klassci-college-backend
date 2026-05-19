"""Service : composition + génération du bordereau journalier (PDF).

Compose le dict `data` attendu par `pdf.daily_cash_book.generate_daily_cash_book_pdf`
depuis tous les Payment d'une date donnée, et délègue au générateur PDF stateless.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.enrollment import Enrollment
from app.models.fee import Payment, PaymentStatus
from app.models.user import User
from app.services._school_settings_helper import (
    load_school_settings_for_pdf as _get_school_settings,
)
from app.services.pdf import generate_daily_cash_book_pdf
from app.services.pdf._helpers import enum_value


async def _load_payments_for_day(db: AsyncSession, target_date: date) -> list[Payment]:
    """Charge tous les paiements de la journée avec student name pour PDF."""
    day_start = datetime.combine(target_date, time.min)
    day_end = day_start + timedelta(days=1)
    stmt = (
        select(Payment)
        .where(Payment.created_at >= day_start, Payment.created_at < day_end)
        .options(
            selectinload(Payment.enrollment).selectinload(Enrollment.student),
        )
        .order_by(Payment.created_at.asc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def _resolve_cashier_name(db: AsyncSession, user_id: int | None) -> str:
    """Nom du caissier ayant clôturé — soit l'user demandeur, soit '—'."""
    if not user_id:
        return "—"
    stmt = select(User).where(User.id == user_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if user is None:
        return "—"
    return user.email.split("@")[0]


def _student_full_name(payment: Payment) -> str:
    enrollment = payment.enrollment
    if enrollment is None:
        return "—"
    student = enrollment.student
    if student is None:
        return "—"
    parts = [student.first_name or "", student.last_name or ""]
    return " ".join(p for p in parts if p).strip() or "—"


async def get_daily_cash_book_pdf(
    db: AsyncSession,
    target_date: date,
    *,
    cashier_user_id: int | None = None,
) -> bytes:
    """Génère le bordereau journalier en PDF pour la date donnée."""
    payments = await _load_payments_for_day(db, target_date)

    payment_rows: list[dict] = []
    totals_by_method: dict[str, Decimal] = {}
    total_general = Decimal("0")
    count_completed = 0
    count_cancelled = 0

    for p in payments:
        # FIX bug enum : extraire .value pour obtenir 'cash' au lieu de PaymentMethod.CASH
        p_method = enum_value(p.method)
        p_status = enum_value(p.status)
        payment_rows.append(
            {
                "id": p.id,
                "created_at": p.created_at,
                "student_name": _student_full_name(p),
                "method": p_method,
                "reference": p.reference,
                "amount": p.amount,
                "status": p_status,
            }
        )
        if p_status == PaymentStatus.COMPLETED.value:
            totals_by_method[p_method] = totals_by_method.get(p_method, Decimal("0")) + p.amount
            total_general += p.amount
            count_completed += 1
        elif p_status == PaymentStatus.CANCELLED.value:
            count_cancelled += 1

    cashier_name = await _resolve_cashier_name(db, cashier_user_id)
    school = await _get_school_settings(db)

    data = {
        "date": datetime.combine(target_date, time.min),
        "cashier_name": cashier_name,
        "payments": payment_rows,
        "totals_by_method": totals_by_method,
        "total_general": total_general,
        "count_completed": count_completed,
        "count_cancelled": count_cancelled,
        "issued_at": datetime.utcnow(),
    }
    return generate_daily_cash_book_pdf(data, school)
