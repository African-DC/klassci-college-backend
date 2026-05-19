"""Génération du reçu PDF — template KLASSCI premium avec breakdown allocation.

Le template `pdf_service.generate_receipt_pdf` accepte une liste
`allocations` qui rend un tableau zebra avec status pills par frais.
Ce service compose `payment_data` depuis l'ORM Payment + allocations.
"""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.fee import Payment
from app.models.user import User
from app.repositories import payment_repository as repo
from app.services._school_settings_helper import (
    load_school_settings_for_pdf as _get_school_settings,
)
from app.services.pdf_service import generate_receipt_pdf


def _fee_description(payment: Payment) -> str:
    """Compose la description courte du versement (1 ligne en-tête PDF)."""
    if payment.enrollment_fee and payment.enrollment_fee.fee_variant:
        cat = payment.enrollment_fee.fee_variant.category
        if cat:
            return cat.name
    allocations = payment.allocations or []
    if not allocations:
        return ""
    if len(allocations) == 1:
        ef = allocations[0].enrollment_fee
        if ef and ef.fee_variant and ef.fee_variant.category:
            return ef.fee_variant.category.name
    return f"Allocation prioritaire sur {len(allocations)} frais"


async def _total_paid_for_fee(db: AsyncSession, fee_id: int) -> Decimal:
    """Total versé sur un frais (toutes allocations COMPLETED). Source de vérité."""
    return await repo.get_total_paid_for_enrollment_fee(db, fee_id)


def _status_after(fee_amount: Decimal, paid_after: Decimal, current_status: str) -> str:
    """Calcule le status apparent à l'instant de l'allocation."""
    if current_status == "waived":
        return "waived"
    if paid_after >= fee_amount:
        return "paid"
    if paid_after > Decimal("0"):
        return "partial"
    return "pending"


async def _build_allocation_breakdown(db: AsyncSession, payment: Payment) -> list[dict]:
    """Liste enrichie pour le tableau PDF — fee_name + amount + cumul + status."""
    breakdown: list[dict] = []
    for allocation in payment.allocations or []:
        ef = allocation.enrollment_fee
        if ef is None:
            continue
        cat_name = ""
        if ef.fee_variant and ef.fee_variant.category:
            cat_name = ef.fee_variant.category.name
        paid_after = await _total_paid_for_fee(db, ef.id)
        breakdown.append(
            {
                "fee_name": cat_name,
                "amount": allocation.amount,
                "fee_total": ef.amount,
                "fee_paid_after": paid_after,
                "status_after": _status_after(ef.amount, paid_after, ef.status),
            }
        )
    return breakdown


async def _resolve_received_by_name(db: AsyncSession, user_id: int | None) -> str:
    """Affiche un nom user lisible (email avant @) ou vide."""
    if not user_id:
        return ""
    user_stmt = select(User).where(User.id == user_id)
    user_result = await db.execute(user_stmt)
    user = user_result.scalar_one_or_none()
    return user.email.split("@")[0] if user else ""


async def get_payment_receipt_pdf(db: AsyncSession, payment_id: int) -> bytes:
    """Génère et retourne un PDF reçu pour un paiement.

    Inclut le breakdown allocation (tableau Frais / Affecté / Cumul / Statut)
    quand le paiement a 2+ allocations. Template KLASSCI premium (palette
    primary/accent, status pills, zebra rows).
    """
    payment = await repo.get_payment_with_allocations(db, payment_id)
    if payment is None:
        raise NotFoundError("Payment", payment_id)

    student_name = ""
    enrollment = payment.enrollment
    if enrollment and enrollment.student:
        s = enrollment.student
        student_name = f"{s.first_name} {s.last_name}"

    school = await _get_school_settings(db)
    received_by_name = await _resolve_received_by_name(db, payment.received_by)
    allocations_breakdown = await _build_allocation_breakdown(db, payment)

    # FIX bug enum : SQLAlchemy SAEnum retourne l'enum object (PaymentMethod.CASH),
    # passer par enum_value() pour obtenir la string brute consommée par les labels FR.
    from app.services.pdf._helpers import enum_value

    payment_data = {
        "payment_id": payment.id,
        "amount": payment.amount,
        "method": enum_value(payment.method),
        "reference": payment.reference,
        "status": enum_value(payment.status),
        "notes": payment.notes,
        "student_name": student_name,
        "fee_description": _fee_description(payment),
        "created_at": payment.created_at,
        "received_by_name": received_by_name,
        # Breakdown affiché dans le PDF dès qu'il y a 2+ frais alloués.
        # Pour les paiements legacy 1:1, on garde la simple ligne fee_description.
        "allocations": allocations_breakdown if len(allocations_breakdown) > 1 else [],
    }

    return generate_receipt_pdf(payment_data, school)
