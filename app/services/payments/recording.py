"""Enregistrement d'un paiement caissier — flow cible + flow legacy.

Le flow cible `record_enrollment_payment` matérialise le métier ivoirien :
caissier saisit montant sur une inscription, allocation auto-prioritaire.
Le flow legacy `create_payment` est conservé pour rétrocompat (POST /payments
granulaire) — il log un warning et crée également 1 PaymentAllocation 1:1
pour rester cohérent avec la nouvelle source de vérité.
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditAction, audit_log
from app.core.dependencies import TokenData
from app.core.exceptions import BusinessValidationError, NotFoundError
from app.core.payment_methods import DRAWER_METHODS
from app.models.fee import EnrollmentFee, EnrollmentFeeStatus, PaymentStatus
from app.repositories import payment_repository as repo
from app.schemas.payment import EnrollmentPaymentCreate, PaymentCreate, PaymentResponse
from app.services import cash_session_service, fees_paid
from app.services.payments import methods as payment_methods
from app.services.payments._allocation import (
    paid_for_fees,
    plan_allocation,
    recompute_fee_status,
)
from app.services.payments._notification import dispatch_payment_notification
from app.services.payments._response import payment_to_response
from app.services.payments._state import logger


async def _guard_method_and_drawer(
    db: AsyncSession, actor: TokenData, method: str, *, when: datetime
) -> None:
    """Les deux conditions à remplir avant d'écrire quoi que ce soit.

    D'abord le droit d'encaisser par ce moyen (établissement puis rôle), ensuite
    le tiroir. Les deux hors transaction, pour que le refus remonte tel quel.

    **Le tiroir ne concerne que les espèces.** La journée de caisse existe parce
    qu'un billet se compte le soir et qu'un écart se constate ; un virement ou
    un versement Wave laisse une trace bancaire ou opérateur et n'a rien à
    compter. La règle était jusqu'ici seulement supposée : ce flux ouvrait une
    journée de caisse pour TOUT versement, y compris un virement encaissé par un
    comptable qui n'a même pas `cash-session:manage` et ne pourra donc jamais la
    clôturer — pendant que le flux legacy, lui, n'en ouvrait aucune et laissait
    passer des espèces sur une journée déjà clôturée.
    """
    await payment_methods.ensure_method_allowed(db, actor, method)
    if method in DRAWER_METHODS:
        await cash_session_service.ensure_open_session(db, actor.user_id, when)


async def record_enrollment_payment(
    db: AsyncSession,
    enrollment_id: int,
    data: EnrollmentPaymentCreate,
    *,
    actor: TokenData,
) -> PaymentResponse:
    """Enregistre un versement à la caisse, auto-alloué par priorité.

    Décisions métier validées 2026-05-17 :
    - Priorité ASC sur `FeeCategory.priority` (Inscription 10 → Tenue 60 → reste 100).
    - Surplus → reject avec message clair (P0). Credit balance différé V2.
    - Override manuel → pas en P0 (priorité stricte).
    - Audit log unique avec breakdown allocation.
    """
    received_by = actor.user_id
    await _guard_method_and_drawer(db, actor, data.method, when=datetime.now())

    async with db.begin_nested():
        enrollment = await repo.get_enrollment_for_update(db, enrollment_id)
        if enrollment is None:
            raise NotFoundError("Enrollment", enrollment_id)

        unpaid_fees = await repo.get_unpaid_fees_ordered_by_priority(db, enrollment_id)
        if not unpaid_fees:
            raise BusinessValidationError(
                "Aucun frais à régler sur cette inscription "
                "(tous payés/exonérés ou frais non configurés)"
            )

        # Une requete groupee pour toute l'inscription, pas une par frais :
        # encaisser sur une inscription a six frais coutait six allers-retours
        # sequentiels a la base, le tiroir ouvert et la famille au guichet.
        deja_verse = await fees_paid.paid_by_enrollment(db, enrollment_id)
        fees_with_paid: list[tuple[EnrollmentFee, Decimal]] = [
            (fee, deja_verse.get(fee.id, Decimal("0"))) for fee in unpaid_fees
        ]
        total_remaining = sum((fee.amount - paid for fee, paid in fees_with_paid), Decimal("0"))

        if data.amount > total_remaining:
            raise BusinessValidationError(
                f"Montant versé ({data.amount} XOF) supérieur à la dette restante "
                f"({total_remaining} XOF). Veuillez ajuster le montant ou créer une "
                f"inscription pour l'année suivante."
            )

        splits, _surplus = plan_allocation(data.amount, fees_with_paid)

        # Tous les moyens complètent immédiatement : la caissière ne saisit un
        # versement qu'une fois l'argent reçu ou le transfert confirmé sur son
        # téléphone. Un état « en attente » pour le virement et le chèque
        # relèverait d'un rapprochement bancaire, qui n'existe pas encore.
        payment = await repo.create_payment(
            db,
            enrollment_id=enrollment_id,
            enrollment_fee_id=None,  # NEW flow — pas de cible granulaire
            amount=data.amount,
            method=data.method,
            status=PaymentStatus.COMPLETED.value,
            reference=data.reference,
            received_by=received_by,
            notes=data.notes,
        )

        for fee, allocated in splits:
            await repo.create_allocation(
                db,
                payment_id=payment.id,
                enrollment_fee_id=fee.id,
                amount=allocated,
            )

        await db.flush()

        # Les statuts se recalculent une fois les allocations écrites, sur un
        # seul relevé groupé : un aller-retour, pas un par frais touché.
        apres = await paid_for_fees(db, [fee for fee, _ in splits])
        for fee, _allocated in splits:
            recompute_fee_status(fee, apres.get(fee.id, Decimal("0")))

        await db.flush()

        await audit_log(
            db,
            entity_type="payment",
            action=AuditAction.CREATE,
            user_id=received_by,
            entity_id=payment.id,
            new_values={
                "enrollment_id": enrollment_id,
                "amount": str(data.amount),
                "method": data.method,
                "reference": data.reference,
                "allocations": [
                    {"enrollment_fee_id": fee.id, "amount": str(allocated)}
                    for fee, allocated in splits
                ],
            },
        )

    await db.commit()

    refreshed = await repo.get_payment_with_allocations(db, payment.id)
    if refreshed is None:
        raise NotFoundError("Payment", payment.id)

    await dispatch_payment_notification(db, refreshed, kind="received")
    return payment_to_response(refreshed)


async def create_payment(
    db: AsyncSession,
    data: PaymentCreate,
    *,
    actor: TokenData,
) -> PaymentResponse:
    """LEGACY — paiement ciblant un frais spécifique.

    Conservé pour rétrocompat (FE caissier non encore refondu). Crée
    aussi une PaymentAllocation 1:1 pour cohérence avec le nouveau modèle.
    Nouveau code → `record_enrollment_payment`.
    """
    logger.warning(
        "POST /payments (legacy) appelé pour enrollment_fee_id=%s. "
        "Préférer POST /enrollments/{id}/payments (auto-allocation).",
        data.enrollment_fee_id,
    )

    received_by = actor.user_id
    await _guard_method_and_drawer(db, actor, data.method, when=datetime.now())

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

        deja_verse = await fees_paid.paid_by_enrollment(db, enrollment_fee.enrollment_id)
        total_paid = deja_verse.get(data.enrollment_fee_id, Decimal("0"))
        remaining = enrollment_fee.amount - total_paid
        if data.amount > remaining:
            raise BusinessValidationError(
                f"Payment amount {data.amount} exceeds remaining balance {remaining}"
            )

        payment = await repo.create_payment(
            db,
            enrollment_id=enrollment_fee.enrollment_id,
            enrollment_fee_id=data.enrollment_fee_id,
            amount=data.amount,
            method=data.method,
            status=PaymentStatus.COMPLETED.value,
            reference=data.reference,
            received_by=received_by,
            notes=data.notes,
        )

        await repo.create_allocation(
            db,
            payment_id=payment.id,
            enrollment_fee_id=data.enrollment_fee_id,
            amount=data.amount,
        )
        await db.flush()

        apres = await paid_for_fees(db, [enrollment_fee])
        recompute_fee_status(enrollment_fee, apres.get(enrollment_fee.id, Decimal("0")))
        await db.flush()

        await audit_log(
            db,
            entity_type="payment",
            action=AuditAction.CREATE,
            user_id=received_by,
            entity_id=payment.id,
            new_values={
                "enrollment_id": enrollment_fee.enrollment_id,
                "enrollment_fee_id": data.enrollment_fee_id,
                "amount": str(data.amount),
                "method": data.method,
                "reference": data.reference,
                "enrollment_fee_status": enrollment_fee.status,
                "legacy_path": True,
            },
        )

    await db.commit()

    refreshed = await repo.get_payment_with_allocations(db, payment.id)
    if refreshed is None:
        raise NotFoundError("Payment", payment.id)

    await dispatch_payment_notification(db, refreshed, kind="received")
    return payment_to_response(refreshed)
