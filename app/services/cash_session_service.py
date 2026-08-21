"""Caisse — ouverture paresseuse, clôture par le caissier, point journalier."""

import logging
from datetime import date as date_type
from datetime import datetime
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditAction, audit_log
from app.core.datetimes import utcnow_naive
from app.core.exceptions import NotFoundError
from app.models.cash_session import CashSession, CashSessionStatus, is_locked
from app.repositories import cash_session_repository as repo
from app.repositories.cash_session_repository import METHODS_ORDER, DayAggregate
from app.schemas.cash_session import (
    CashMethodTotal,
    CashSessionCloseRequest,
    CashSessionListResponse,
    CashSessionResponse,
)
from app.services.pdf.theme import method_label

logger = logging.getLogger(__name__)


def _method_totals(aggregate: DayAggregate) -> list[CashMethodTotal]:
    """Ventilation ordonnée, en n'affichant que les moyens réellement utilisés.

    Afficher « Chèque : 0 » sur une école qui n'en accepte pas ajoute du bruit
    sans rien apprendre.
    """
    return [
        CashMethodTotal(
            method=key,
            label=method_label(key),
            count=aggregate.by_method[key].count,
            total=float(aggregate.by_method[key].total),
        )
        for key in METHODS_ORDER
        if key in aggregate.by_method
    ]


def to_response(
    session: CashSession, *, cashier_name: str, aggregate: DayAggregate | None
) -> CashSessionResponse:
    """Assemble une session avec ses agrégats.

    `aggregate` accepte `None` : une journée sans aucun versement n'a pas de
    ligne d'agrégat, et retomber sur des zéros vaut mieux que de la faire
    disparaître de l'écran.

    Une session clôturée garde `expected_amount`, `counted_amount` et
    `variance` figés au moment de la clôture : les recalculer ferait bouger un
    écart déjà constaté et signé.
    """
    aggregate = aggregate or DayAggregate()
    status = str(getattr(session.status, "value", session.status))
    return CashSessionResponse(
        id=session.id,
        cashier_user_id=session.cashier_user_id,
        cashier_name=cashier_name,
        business_date=session.business_date,
        status=status,
        opened_at=session.opened_at,
        closed_at=session.closed_at,
        counted_amount=(
            float(session.counted_amount) if session.counted_amount is not None else None
        ),
        expected_amount=(
            float(session.expected_amount) if session.expected_amount is not None else None
        ),
        variance=float(session.variance) if session.variance is not None else None,
        regularized_at=session.regularized_at,
        notes=session.notes,
        payments_count=aggregate.count,
        total_collected=float(aggregate.total),
        cash_collected=float(aggregate.cash_total),
        by_method=_method_totals(aggregate),
    )


async def ensure_open_session(db: AsyncSession, cashier_user_id: int, when: datetime) -> None:
    """Ouvre la journée du caissier au premier encaissement, si besoin.

    Volontairement paresseux : imposer un « ouvrir ma caisse » avant le premier
    versement bloquerait le guichet le matin, avec la file déjà devant. Refuse
    en revanche d'encaisser sur une journée clôturée — l'écart signé serait
    faux la seconde suivante.
    """
    business_date = when.date()
    session = await repo.get_session(db, cashier_user_id, business_date)
    if session is None:
        await repo.create_session(db, cashier_user_id, business_date, opened_at=when)
        return
    if is_locked(session.status):
        raise HTTPException(
            status_code=409,
            detail=(
                "Votre caisse du jour est déjà clôturée. Contactez la comptabilité "
                "pour enregistrer ce versement."
            ),
        )


async def get_my_session(
    db: AsyncSession, cashier_user_id: int, business_date: date_type
) -> CashSessionResponse:
    """Ma caisse. La session est créée si elle n'existe pas encore.

    Ouvrir l'écran avant le premier encaissement de la journée est le cas
    normal : renvoyer un 404 obligerait le front à inventer une journée vide,
    et le caissier ne pourrait pas clôturer une journée sans versement.
    """
    session = await repo.get_session(db, cashier_user_id, business_date)
    if session is None:
        session = await repo.create_session(
            db,
            cashier_user_id,
            business_date,
            opened_at=datetime.combine(business_date, datetime.min.time()),
        )
        await db.commit()
        refreshed = await repo.get_session_by_id(db, session.id)
        if refreshed is None:
            raise NotFoundError("CashSession", session.id)
        session = refreshed

    aggregate = await repo.aggregate_day(db, cashier_user_id, business_date)
    names = await repo.cashier_names(db, [cashier_user_id])
    return to_response(session, cashier_name=names.get(cashier_user_id, "—"), aggregate=aggregate)


async def close_my_session(
    db: AsyncSession,
    cashier_user_id: int,
    business_date: date_type,
    data: CashSessionCloseRequest,
) -> CashSessionResponse:
    """Clôture : fige le théorique, calcule l'écart, verrouille la journée."""
    session = await repo.get_session(db, cashier_user_id, business_date)
    if session is None:
        raise NotFoundError("CashSession", 0)
    if session.status == CashSessionStatus.AUTO_CLOSED:
        raise HTTPException(
            status_code=409,
            detail=(
                "Cette journée a été clôturée d'office à minuit. Régularisez-la en "
                "saisissant ce que vous avez compté."
            ),
        )
    if is_locked(session.status):
        raise HTTPException(status_code=409, detail="Cette journée de caisse est déjà clôturée.")

    aggregate = await repo.aggregate_day(db, cashier_user_id, business_date)
    expected = aggregate.cash_total
    counted = Decimal(str(data.counted_amount))

    async with db.begin_nested():
        session.status = CashSessionStatus.CLOSED
        session.closed_at = utcnow_naive()
        session.expected_amount = expected
        session.counted_amount = counted
        session.variance = counted - expected
        session.notes = data.notes
        await audit_log(
            db,
            entity_type="cash_session",
            action=AuditAction.UPDATE,
            user_id=cashier_user_id,
            entity_id=session.id,
            new_values={
                "status": CashSessionStatus.CLOSED.value,
                "business_date": business_date.isoformat(),
                "expected_amount": float(expected),
                "counted_amount": float(counted),
                "variance": float(counted - expected),
            },
        )
    await db.commit()

    refreshed = await repo.get_session_by_id(db, session.id)
    if refreshed is None:
        raise NotFoundError("CashSession", session.id)
    names = await repo.cashier_names(db, [cashier_user_id])
    return to_response(refreshed, cashier_name=names.get(cashier_user_id, "—"), aggregate=aggregate)


async def get_daily_point(db: AsyncSession, business_date: date_type) -> CashSessionListResponse:
    """Point journalier du comptable : toutes les caisses, clôturées ou non.

    Trois requêtes au total quel que soit le nombre de caisses : les sessions,
    leurs agrégats groupés, puis les noms.
    """
    sessions = await repo.list_sessions_for_date(db, business_date)
    aggregates = await repo.aggregate_date_by_cashier(db, business_date)
    names = await repo.cashier_names(db, [s.cashier_user_id for s in sessions])

    items = [
        to_response(
            session,
            cashier_name=names.get(session.cashier_user_id, "—"),
            aggregate=aggregates.get(session.cashier_user_id, DayAggregate()),
        )
        for session in sessions
    ]

    return CashSessionListResponse(
        items=items,
        business_date=business_date,
        total_collected=sum(i.total_collected for i in items),
        cash_collected=sum(i.cash_collected for i in items),
        total_variance=sum(i.variance or 0.0 for i in items),
        open_count=sum(1 for i in items if i.status == CashSessionStatus.OPEN.value),
        closed_count=sum(1 for i in items if i.status == CashSessionStatus.CLOSED.value),
        auto_closed_count=sum(1 for i in items if i.status == CashSessionStatus.AUTO_CLOSED.value),
    )
