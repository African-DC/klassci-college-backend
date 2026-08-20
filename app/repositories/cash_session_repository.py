"""Accès données de la caisse — sessions et agrégats de versements par journée."""

from dataclasses import dataclass, field
from datetime import date as date_type
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Date, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.cash_session import CashSession, CashSessionStatus
from app.models.fee import Payment, PaymentStatus
from app.models.user import StaffProfile, User

# Les versements annulés, échoués ou remboursés ne sont plus dans le tiroir :
# ils ne comptent ni dans le total encaissé ni dans le théorique espèces.
_COUNTED_STATUSES = (PaymentStatus.COMPLETED.value, PaymentStatus.PENDING.value)

# Ordre d'affichage des moyens de paiement. Source unique : le PDF du bordereau
# l'importe d'ici plutôt que d'en garder une copie.
METHODS_ORDER: tuple[str, ...] = ("cash", "mobile_money", "bank_transfer", "cheque")


@dataclass(frozen=True, slots=True)
class MethodTotal:
    count: int
    total: Decimal


@dataclass(frozen=True, slots=True)
class DayAggregate:
    """Ce qu'un caissier a encaissé sur une journée, ventilé par moyen.

    Typé plutôt que rendu en `dict[str, object]` : le dictionnaire obligeait
    chaque lecture à un cast, et faisait proliférer les `type: ignore` dans le
    service au lieu de rendre le contrat explicite.
    """

    count: int = 0
    total: Decimal = Decimal("0")
    cash_total: Decimal = Decimal("0")
    by_method: dict[str, MethodTotal] = field(default_factory=dict)


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


def _fold_rows(rows: list[tuple[object, object, object]]) -> DayAggregate:
    by_method: dict[str, MethodTotal] = {}
    total = Decimal("0")
    count = 0
    for method, method_count, method_total in rows:
        key = str(getattr(method, "value", method))
        amount = Decimal(str(method_total or 0))
        by_method[key] = MethodTotal(count=int(method_count), total=amount)  # type: ignore[arg-type]
        total += amount
        count += int(method_count)  # type: ignore[arg-type]
    cash = by_method.get("cash")
    return DayAggregate(
        count=count,
        total=total,
        cash_total=cash.total if cash else Decimal("0"),
        by_method=by_method,
    )


async def aggregate_day(
    db: AsyncSession, cashier_user_id: int, business_date: date_type
) -> DayAggregate:
    """Ce qu'un caissier a encaissé ce jour-là, ventilé par moyen."""
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
    return _fold_rows(list((await db.execute(stmt)).all()))


async def aggregate_date_by_cashier(
    db: AsyncSession, business_date: date_type
) -> dict[int, DayAggregate]:
    """Agrégats de TOUTES les caisses d'une date, en une seule requête.

    Le point journalier appelait `aggregate_day` par caisse : cinq caissiers
    valaient cinq requêtes d'agrégat, plus les noms. C'est l'écran que le
    comptable ouvre chaque soir.
    """
    stmt = (
        select(
            Payment.received_by,
            Payment.method,
            func.count(Payment.id),
            func.coalesce(func.sum(Payment.amount), 0),
        )
        .where(
            cast(Payment.created_at, Date) == business_date,
            Payment.received_by.is_not(None),
            Payment.status.in_(_COUNTED_STATUSES),
        )
        .group_by(Payment.received_by, Payment.method)
    )
    grouped: dict[int, list[tuple[object, object, object]]] = {}
    for cashier_id, method, method_count, method_total in (await db.execute(stmt)).all():
        grouped.setdefault(int(cashier_id), []).append((method, method_count, method_total))
    return {cashier_id: _fold_rows(rows) for cashier_id, rows in grouped.items()}


async def cashier_names(db: AsyncSession, user_ids: list[int]) -> dict[int, str]:
    """Nom lisible de chaque caissier, en une requête au lieu d'une par ligne.

    La fiche Personnel fait foi ; à défaut, l'email, qui vaut toujours mieux
    qu'un tiret pour identifier qui a encaissé.
    """
    if not user_ids:
        return {}
    stmt = (
        select(User.id, User.email, StaffProfile.first_name, StaffProfile.last_name)
        .outerjoin(StaffProfile, StaffProfile.user_id == User.id)
        .where(User.id.in_(user_ids))
    )
    names: dict[int, str] = {}
    for user_id, email, first_name, last_name in (await db.execute(stmt)).all():
        full = f"{first_name or ''} {last_name or ''}".strip()
        names[int(user_id)] = full or email
    return names


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
