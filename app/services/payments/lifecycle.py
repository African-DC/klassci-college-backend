"""Transitions de statut Payment : validate (pending → completed) + cancel.

Cancel d'un paiement alloué à N fees cascade DELETE allocations (FK) puis
recompute chaque fee.status. Audit log obligatoire avec breakdown
(snapshot des allocations avant suppression) — décision Marcel #4.
"""

from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.audit import AuditAction, audit_log
from app.core.exceptions import NotFoundError
from app.models.fee import Payment, PaymentAllocation, PaymentStatus
from app.repositories import payment_repository as repo
from app.schemas.payment import PaymentResponse
from app.services.payments._allocation import paid_for_fees, recompute_fee_status
from app.services.payments._notification import dispatch_payment_notification
from app.services.payments._response import payment_to_response
from app.services.payments._state import VALID_TRANSITIONS


async def _load_payment_for_transition(db: AsyncSession, payment_id: int) -> Payment:
    """Lock un Payment + ses allocations pour transition de statut."""
    stmt = (
        select(Payment)
        .where(Payment.id == payment_id)
        .options(
            selectinload(Payment.allocations).selectinload(PaymentAllocation.enrollment_fee),
        )
        .with_for_update(of=Payment)
    )
    result = await db.execute(stmt)
    payment = result.scalar_one_or_none()
    if payment is None:
        raise NotFoundError("Payment", payment_id)
    return payment


def _ensure_transition_allowed(current: str, target: str) -> None:
    if target not in VALID_TRANSITIONS.get(current, []):
        raise HTTPException(
            status_code=409,
            detail=f"Transition invalide : impossible de passer de '{current}' à '{target}'",
        )


async def validate_payment(
    db: AsyncSession,
    payment_id: int,
    *,
    validated_by: int,
) -> PaymentResponse:
    """Transition un paiement de pending à completed + recalcul fees impactés."""
    async with db.begin_nested():
        payment = await _load_payment_for_transition(db, payment_id)
        current = payment.status
        _ensure_transition_allowed(current, "completed")

        payment.status = PaymentStatus.COMPLETED.value
        await db.flush()

        touches = []
        for allocation in payment.allocations:
            fee = await repo.get_enrollment_fee_for_update(db, allocation.enrollment_fee_id)
            if fee is not None:
                touches.append(fee)
        verses = await paid_for_fees(db, touches)
        for fee in touches:
            recompute_fee_status(fee, verses.get(fee.id, Decimal("0")))
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

    refreshed = await repo.get_payment_with_allocations(db, payment.id)
    if refreshed is None:
        raise NotFoundError("Payment", payment.id)

    await dispatch_payment_notification(db, refreshed, kind="validated")
    return payment_to_response(refreshed)


async def _ensure_cashier_may_cancel(db: AsyncSession, payment: Payment, cashier_id: int) -> None:
    """Un caissier ne corrige que sa propre saisie, journée encore ouverte."""
    from app.repositories import cash_session_repository as cash_repo

    if payment.received_by != cashier_id:
        raise HTTPException(
            status_code=403,
            detail=(
                "Ce versement a été encaissé par une autre caisse. "
                "Demandez la correction à la comptabilité."
            ),
        )
    if await cash_repo.has_closed_session(db, cashier_id, payment.created_at.date()):
        raise HTTPException(
            status_code=409,
            detail=(
                "Votre journée de caisse est clôturée : ce versement ne peut plus être "
                "annulé ici. Demandez la correction à la comptabilité."
            ),
        )


async def cancel_payment(
    db: AsyncSession,
    payment_id: int,
    *,
    cancelled_by: int,
    may_cancel_any: bool,
) -> PaymentResponse:
    """Annule un paiement et recalcule les statuts de TOUS les fees alloués.

    À l'annulation d'un payment alloué à N fees, cascade DELETE allocations
    + recalcule chaque fee.status. Audit log obligatoire avec breakdown.

    `may_cancel_any` est sans valeur par défaut à dessein : c'est un garde de
    sécurité, et un défaut permissif le désactiverait en silence chez le
    premier appelant qui l'oublierait. `False` correspond au caissier — il ne
    corrige qu'un versement qu'il a lui-même saisi, et seulement tant que sa
    journée n'est pas clôturée. Après clôture, l'écart a été constaté et signé,
    revenir dessus rendrait faux un document déjà remis.
    """
    async with db.begin_nested():
        payment = await _load_payment_for_transition(db, payment_id)
        current = payment.status
        _ensure_transition_allowed(current, "cancelled")

        if not may_cancel_any:
            await _ensure_cashier_may_cancel(db, payment, cancelled_by)

        # Snapshot des allocations pour l'audit avant la transition
        allocations_snapshot = [
            {"enrollment_fee_id": a.enrollment_fee_id, "amount": str(a.amount)}
            for a in payment.allocations
        ]
        affected_fee_ids = [a.enrollment_fee_id for a in payment.allocations]

        payment.status = PaymentStatus.CANCELLED.value
        await db.flush()

        touches = []
        for fee_id in affected_fee_ids:
            fee = await repo.get_enrollment_fee_for_update(db, fee_id)
            if fee is not None:
                touches.append(fee)
        verses = await paid_for_fees(db, touches)
        for fee in touches:
            recompute_fee_status(fee, verses.get(fee.id, Decimal("0")))
        await db.flush()

        await audit_log(
            db,
            entity_type="payment",
            action=AuditAction.UPDATE,
            user_id=cancelled_by,
            entity_id=payment.id,
            old_values={"status": current},
            new_values={
                "status": payment.status,
                "cancelled_allocations": allocations_snapshot,
                "recomputed_fee_ids": affected_fee_ids,
            },
        )

    await db.commit()

    refreshed = await repo.get_payment_with_allocations(db, payment.id)
    if refreshed is None:
        raise NotFoundError("Payment", payment.id)
    return payment_to_response(refreshed)
