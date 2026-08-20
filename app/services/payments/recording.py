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
from app.core.exceptions import BusinessValidationError, NotFoundError
from app.models.fee import EnrollmentFee, EnrollmentFeeStatus, PaymentStatus
from app.repositories import payment_repository as repo
from app.schemas.payment import EnrollmentPaymentCreate, PaymentCreate, PaymentResponse
from app.services import cash_session_service
from app.services.payments._allocation import plan_allocation, recompute_fee_status
from app.services.payments._notification import dispatch_payment_notification
from app.services.payments._response import payment_to_response
from app.services.payments._state import logger


async def _ensure_method_accepted(db: AsyncSession, method: str) -> None:
    """Refuse un moyen de paiement que l'établissement n'accepte pas.

    La colonne vaut `NULL` tant que l'école n'a rien configuré, et signifie
    alors « tous acceptés » : les établissements déjà en service ne doivent
    pas voir leurs encaissements bloqués par une option qu'ils n'ont jamais
    remplie.
    """
    from sqlalchemy import select

    from app.models.academic import SchoolSettings

    stmt = select(SchoolSettings.enabled_payment_methods).limit(1)
    configured = (await db.execute(stmt)).scalar_one_or_none()
    if not configured:
        return

    accepted = {key.strip() for key in configured.split(",") if key.strip()}
    if method not in accepted:
        raise BusinessValidationError(
            f"L'établissement n'accepte pas ce moyen de paiement. "
            f"Moyens acceptés : {', '.join(sorted(accepted))}."
        )


async def record_enrollment_payment(
    db: AsyncSession,
    enrollment_id: int,
    data: EnrollmentPaymentCreate,
    *,
    received_by: int,
) -> PaymentResponse:
    """Enregistre un versement à la caisse, auto-alloué par priorité.

    Décisions métier validées 2026-05-17 :
    - Priorité ASC sur `FeeCategory.priority` (Inscription 10 → Tenue 60 → reste 100).
    - Surplus → reject avec message clair (P0). Credit balance différé V2.
    - Override manuel → pas en P0 (priorité stricte).
    - Audit log unique avec breakdown allocation.
    """
    await _ensure_method_accepted(db, data.method)

    # Ouvre la journée de caisse au premier versement, et refuse d'encaisser
    # sur une journée déjà clôturée : l'écart signé le serait sur un total
    # devenu faux. Hors transaction pour que le refus remonte tel quel.
    await cash_session_service.ensure_open_session(db, received_by, datetime.now())

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

        fees_with_paid: list[tuple[EnrollmentFee, Decimal]] = []
        total_remaining = Decimal("0")
        for fee in unpaid_fees:
            paid = await repo.get_total_paid_for_enrollment_fee(db, fee.id)
            fees_with_paid.append((fee, paid))
            total_remaining += fee.amount - paid

        if data.amount > total_remaining:
            raise BusinessValidationError(
                f"Montant versé ({data.amount} XOF) supérieur à la dette restante "
                f"({total_remaining} XOF). Veuillez ajuster le montant ou créer une "
                f"inscription pour l'année suivante."
            )

        splits, _surplus = plan_allocation(data.amount, fees_with_paid)

        # Cash/mobile_money complete immédiatement. bank_transfer/cheque
        # pourraient passer en pending dans une seconde itération (validation manuelle).
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
            await recompute_fee_status(db, fee)

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
    received_by: int,
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

        total_paid = await repo.get_total_paid_for_enrollment_fee(db, data.enrollment_fee_id)
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

        await recompute_fee_status(db, enrollment_fee)
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
