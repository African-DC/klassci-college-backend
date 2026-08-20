"""Caisse — ouverture paresseuse, clôture par le caissier, point journalier."""

import logging
from datetime import date as date_type
from datetime import datetime
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditAction, audit_log
from app.core.exceptions import NotFoundError
from app.models.cash_session import CashSession, CashSessionStatus
from app.models.user import StaffProfile, User
from app.repositories import cash_session_repository as repo
from app.schemas.cash_session import (
    CashMethodTotal,
    CashSessionCloseRequest,
    CashSessionListResponse,
    CashSessionResponse,
)
from app.services.pdf.theme import method_label

logger = logging.getLogger(__name__)

_METHODS_ORDER = ("cash", "mobile_money", "bank_transfer", "cheque")


async def _cashier_display_name(db: AsyncSession, user_id: int) -> str:
    """Nom lisible du caissier : sa fiche Personnel, sinon son email."""
    stmt = select(StaffProfile).where(StaffProfile.user_id == user_id)
    profile = (await db.execute(stmt)).scalar_one_or_none()
    if profile is not None:
        full = f"{profile.first_name or ''} {profile.last_name or ''}".strip()
        if full:
            return full
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    return user.email if user is not None else "—"


def _method_totals(by_method: dict[str, dict[str, object]]) -> list[CashMethodTotal]:
    """Ventilation ordonnée, en n'affichant que les moyens réellement utilisés."""
    totals: list[CashMethodTotal] = []
    for key in _METHODS_ORDER:
        entry = by_method.get(key)
        if entry is None:
            continue
        totals.append(
            CashMethodTotal(
                method=key,
                label=method_label(key),
                count=int(entry["count"]),  # type: ignore[arg-type]
                total=float(entry["total"]),  # type: ignore[arg-type]
            )
        )
    return totals


async def _to_response(
    db: AsyncSession,
    session: CashSession | None,
    *,
    cashier_user_id: int,
    business_date: date_type,
) -> CashSessionResponse:
    """Assemble une session avec ses agrégats.

    Une session clôturée garde les montants figés au moment de la clôture :
    recalculer ferait bouger un écart déjà constaté et signé.
    """
    aggregate = await repo.aggregate_day(db, cashier_user_id, business_date)
    name = await _cashier_display_name(db, cashier_user_id)

    if session is None:
        # Encaissements sans session : versements antérieurs à la mise en place
        # des sessions. On les présente comme une journée ouverte, sinon
        # l'argent encaissé n'apparaîtrait nulle part.
        return CashSessionResponse(
            id=0,
            cashier_user_id=cashier_user_id,
            cashier_name=name,
            business_date=business_date,
            status=CashSessionStatus.OPEN.value,
            opened_at=datetime.combine(business_date, datetime.min.time()),
            payments_count=int(aggregate["count"]),  # type: ignore[arg-type]
            total_collected=float(aggregate["total"]),  # type: ignore[arg-type]
            cash_collected=float(aggregate["cash_total"]),  # type: ignore[arg-type]
            by_method=_method_totals(aggregate["by_method"]),  # type: ignore[arg-type]
        )

    return CashSessionResponse(
        id=session.id,
        cashier_user_id=session.cashier_user_id,
        cashier_name=name,
        business_date=session.business_date,
        status=session.status if isinstance(session.status, str) else session.status.value,
        opened_at=session.opened_at,
        closed_at=session.closed_at,
        counted_amount=float(session.counted_amount)
        if session.counted_amount is not None
        else None,
        expected_amount=(
            float(session.expected_amount) if session.expected_amount is not None else None
        ),
        variance=float(session.variance) if session.variance is not None else None,
        notes=session.notes,
        payments_count=int(aggregate["count"]),  # type: ignore[arg-type]
        total_collected=float(aggregate["total"]),  # type: ignore[arg-type]
        cash_collected=float(aggregate["cash_total"]),  # type: ignore[arg-type]
        by_method=_method_totals(aggregate["by_method"]),  # type: ignore[arg-type]
    )


async def ensure_open_session(db: AsyncSession, cashier_user_id: int, when: datetime) -> None:
    """Ouvre la journée du caissier au premier encaissement, si besoin.

    Volontairement paresseux : imposer un « ouvrir ma caisse » avant le
    premier versement bloquerait le guichet le matin, avec la file devant.
    Refuse en revanche d'encaisser sur une journée déjà clôturée — sinon
    l'écart signé serait faux dès la seconde qui suit.
    """
    business_date = when.date()
    session = await repo.get_session(db, cashier_user_id, business_date)
    if session is None:
        await repo.create_session(db, cashier_user_id, business_date, opened_at=when)
        return
    if session.status == CashSessionStatus.CLOSED:
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
    session = await repo.get_session(db, cashier_user_id, business_date)
    return await _to_response(
        db, session, cashier_user_id=cashier_user_id, business_date=business_date
    )


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
    if session.status == CashSessionStatus.CLOSED:
        raise HTTPException(status_code=409, detail="Cette journée de caisse est déjà clôturée.")

    aggregate = await repo.aggregate_day(db, cashier_user_id, business_date)
    expected = Decimal(str(aggregate["cash_total"]))
    counted = Decimal(str(data.counted_amount))

    async with db.begin_nested():
        session.status = CashSessionStatus.CLOSED
        session.closed_at = datetime.now()
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
    return await _to_response(
        db, refreshed, cashier_user_id=cashier_user_id, business_date=business_date
    )


async def get_daily_point(db: AsyncSession, business_date: date_type) -> CashSessionListResponse:
    """Point journalier du comptable : toutes les caisses, clôturées ou non."""
    sessions = await repo.list_sessions_for_date(db, business_date)
    known = {s.cashier_user_id: s for s in sessions}

    # Un caissier qui a encaissé sans session enregistrée doit apparaître :
    # son argent existe même si la ligne de session manque.
    for cashier_id, _email in await repo.list_cashier_ids_with_payments(db, business_date):
        known.setdefault(cashier_id, None)  # type: ignore[arg-type]

    items = [
        await _to_response(db, session, cashier_user_id=cashier_id, business_date=business_date)
        for cashier_id, session in sorted(known.items())
    ]

    return CashSessionListResponse(
        items=items,
        business_date=business_date,
        total_collected=sum(i.total_collected for i in items),
        cash_collected=sum(i.cash_collected for i in items),
        total_variance=sum(i.variance or 0.0 for i in items),
        open_count=sum(1 for i in items if i.status == CashSessionStatus.OPEN.value),
        closed_count=sum(1 for i in items if i.status == CashSessionStatus.CLOSED.value),
    )
