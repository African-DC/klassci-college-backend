"""Accès données de la caisse — sessions et agrégats de versements par journée."""

from datetime import date as date_type
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Date, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.cash_session import CashSession, CashSessionStatus
from app.models.fee import Payment, PaymentStatus
from app.models.user import User

# Les versements annulés, échoués ou remboursés ne sont plus dans le tiroir :
# ils ne doivent compter ni dans le total encaissé ni dans le théorique espèces.
_COUNTED_STATUSES = (PaymentStatus.COMPLETED.value, PaymentStatus.PENDING.value)


async def get_session(
    db: AsyncSession, cashier_user_id: int, business_date: date_type
) -> CashSession | None:
    stmt = (
        select(CashSession)
        .where(
            CashSession.cashier_user_id == cashier_user_id,
            CashSession.business_date == business_date,
        )
        .options(selectinload(CashSession.cashier))
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_session_by_id(db: AsyncSession, session_id: int) -> CashSession | None:
    stmt = (
        select(CashSession)
        .where(CashSession.id == session_id)
        .options(selectinload(CashSession.cashier))
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def create_session(
    db: AsyncSession, cashier_user_id: int, business_date: date_type, *, opened_at: datetime
) -> CashSession:
    session = CashSession(
        cashier_user_id=cashier_user_id,
        business_date=business_date,
        status=CashSessionStatus.OPEN,
        opened_at=opened_at,
    )
    db.add(session)
    await db.flush()
    return session


async def list_sessions_for_date(db: AsyncSession, business_date: date_type) -> list[CashSession]:
    stmt = (
        select(CashSession)
        .where(CashSession.business_date == business_date)
        .options(selectinload(CashSession.cashier))
        .order_by(CashSession.opened_at)
    )
    return list((await db.execute(stmt)).scalars().all())


async def list_cashier_ids_with_payments(
    db: AsyncSession, business_date: date_type
) -> list[tuple[int, str]]:
    """Caissiers ayant encaissé ce jour-là, même sans session enregistrée.

    Les versements antérieurs à la mise en place des sessions n'en ont
    aucune : sans ce balayage, le point journalier d'une date passée
    afficherait une page vide alors que de l'argent est bien entré.
    """
    stmt = (
        select(Payment.received_by, User.email)
        .join(User, User.id == Payment.received_by)
        .where(
            cast(Payment.created_at, Date) == business_date,
            Payment.received_by.is_not(None),
            Payment.status.in_(_COUNTED_STATUSES),
        )
        .group_by(Payment.received_by, User.email)
    )
    rows = (await db.execute(stmt)).all()
    return [(row[0], row[1]) for row in rows]


async def aggregate_day(
    db: AsyncSession, cashier_user_id: int, business_date: date_type
) -> dict[str, object]:
    """Compte et ventile par moyen ce qu'un caissier a encaissé ce jour-là."""
    stmt = (
        select(
            Payment.method,
            func.count(Payment.id),
            func.coalesce(func.sum(Payment.amount), 0),
        )
        .where(
            Payment.received_by == cashier_user_id,
            cast(Payment.created_at, Date) == business_date,
            Payment.status.in_(_COUNTED_STATUSES),
        )
        .group_by(Payment.method)
    )
    rows = (await db.execute(stmt)).all()

    by_method: dict[str, dict[str, object]] = {}
    total = Decimal("0")
    count = 0
    for method, method_count, method_total in rows:
        key = getattr(method, "value", method)
        amount = Decimal(str(method_total or 0))
        by_method[key] = {"count": int(method_count), "total": amount}
        total += amount
        count += int(method_count)

    cash_entry = by_method.get("cash")
    cash_total = cash_entry["total"] if cash_entry else Decimal("0")

    return {
        "count": count,
        "total": total,
        "cash_total": cash_total,
        "by_method": by_method,
    }


async def has_closed_session(
    db: AsyncSession, cashier_user_id: int, business_date: date_type
) -> bool:
    """Vrai si la journée de ce caissier est déjà verrouillée."""
    stmt = select(func.count(CashSession.id)).where(
        CashSession.cashier_user_id == cashier_user_id,
        CashSession.business_date == business_date,
        CashSession.status == CashSessionStatus.CLOSED,
    )
    return bool((await db.execute(stmt)).scalar_one())
