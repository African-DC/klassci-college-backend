"""Transitions de statut Payment : validate (pending → completed) + cancel.

Cancel d'un paiement alloué à N fees garde ses allocations et recalcule
recompute chaque fee.status. Audit log obligatoire avec breakdown
(snapshot des allocations avant suppression) — décision Marcel #4.
"""

from datetime import UTC, datetime
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.audit import AuditAction, audit_log
from app.core.exceptions import BusinessValidationError, NotFoundError
from app.models.fee import Payment, PaymentAllocation, PaymentStatus
from app.repositories import payment_repository as repo
from app.schemas.payment import PaymentResponse
from app.services.payments._allocation import paid_for_fees, recompute_fee_status
from app.services.payments._notification import dispatch_payment_notification
from app.services.payments._response import payment_to_response
from app.services.payments._state import VALID_TRANSITIONS, status_value


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


def _ensure_transition_allowed(current: object, target: str) -> None:
    """Refuse une transition de statut interdite, en nommant l'état lisible.

    Le message part au guichet : il doit dire « completed », pas
    « PaymentStatus.COMPLETED ». Voir `status_value`.
    """
    current_value = status_value(current)
    if target not in VALID_TRANSITIONS.get(current_value, []):
        raise HTTPException(
            status_code=409,
            detail=f"Transition invalide : impossible de passer de '{current_value}' à '{target}'",
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
            old_values={"status": status_value(current)},
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
    if await cash_repo.is_day_locked(db, cashier_id, payment.created_at.date()):
        raise HTTPException(
            status_code=409,
            detail=(
                "Votre journée de caisse est clôturée : ce versement ne peut plus être "
                "annulé ici. Demandez la correction à la comptabilité."
            ),
        )


#: La longueur minimale d'un motif d'annulation, une fois les espaces réduits.
#: L'écran mesure la même chose, sur la même chaîne normalisée.
MOTIF_MINIMUM = 10

#: La colonne fait 500 caractères ; au-delà MySQL tronquerait sans le dire.
MOTIF_MAXIMUM = 500


def _motif_valide(motif: str) -> str:
    """Un motif court n'est pas un motif.

    « erreur », « test », « ok » ne disent rien a qui relira le bordereau dans
    six mois — et c'est precisement a ce moment qu'on le relit. On exige une
    phrase, pas un mot.
    """
    propre = " ".join(motif.split())
    if len(propre) < MOTIF_MINIMUM:
        raise BusinessValidationError(
            "Indiquez le motif de l'annulation en une phrase : elle figurera sur "
            "le bordereau de caisse et sur le reçu."
        )
    return propre[:MOTIF_MAXIMUM]


async def cancel_payment(
    db: AsyncSession,
    payment_id: int,
    *,
    reason: str,
    cancelled_by: int,
    may_cancel_any: bool,
) -> PaymentResponse:
    """Contre-passe un versement : il reste, marqué annulé, avec sa raison.

    On ne supprime pas une écriture de caisse, on l'annule en laissant une
    trace au moins aussi visible que l'encaissement — c'est le principe
    d'intangibilité, et c'est aussi la seule parade au caissier qui
    encaisserait puis effacerait. Le motif est donc obligatoire : il figure sur
    le bordereau et sur le reçu réimprimé.

    **Les allocations survivent** — c'est l'historique de la famille, et le
    guichet le lui montre. Elles cessent de compter parce que tous les totaux
    joignent `Payment` et filtrent `status == 'completed'` : ne jamais écrire
    un consommateur d'allocations sans ce filtre, sous peine de ressusciter de
    l'argent annulé dans un solde.

    Les statuts de TOUS les frais touchés sont recalculés dans la même
    transaction : un solde à moitié rendu serait pire qu'un solde faux, parce
    qu'il aurait l'air juste.

    Ne sert que le cas où **aucun argent n'a bougé** : une saisie en trop, un
    double. Un encaissement réel mais non dû se rembourse ou se reporte en
    avoir — l'annuler ferait disparaître un billet qui est dans le tiroir, et
    la caisse serait en excédent inexpliqué à la clôture. Une imputation sur
    le mauvais frais se ré-affecte. Ni l'un ni l'autre n'existe encore.

    `may_cancel_any` est sans valeur par défaut à dessein : c'est un garde de
    sécurité, et un défaut permissif le désactiverait en silence chez le
    premier appelant qui l'oublierait. `False` correspond au caissier — il ne
    corrige qu'un versement qu'il a lui-même saisi, et seulement tant que sa
    journée n'est pas clôturée. Après clôture, l'écart a été constaté et signé,
    revenir dessus rendrait faux un document déjà remis.
    """
    motif = _motif_valide(reason)

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
        payment.cancelled_at = datetime.now(UTC).replace(tzinfo=None)
        payment.cancelled_by = cancelled_by
        payment.cancellation_reason = motif
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
            old_values={"status": status_value(current)},
            new_values={
                "status": payment.status,
                "cancellation_reason": motif,
                "cancelled_allocations": allocations_snapshot,
                "recomputed_fee_ids": affected_fee_ids,
            },
        )

    await db.commit()

    refreshed = await repo.get_payment_with_allocations(db, payment.id)
    if refreshed is None:
        raise NotFoundError("Payment", payment.id)
    return payment_to_response(refreshed)
