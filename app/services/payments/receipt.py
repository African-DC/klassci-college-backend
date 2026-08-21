"""Composition du reçu de versement : le paiement, l'élève, sa situation.

Le PDF sort en deux exemplaires sur une A4 (voir `pdf/receipt.py`). Ce service
rassemble ce qu'ils affichent : le versement encaissé, l'identité de l'élève,
et le tableau des frais qui dit ce qu'il reste à payer.

Aucun montant n'est calculé ici. Le versé vient de `fee_situation`, qui
s'appuie lui-même sur `fees_paid` ; l'échéance vient de `resolve_schedule`.
"""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.fee import Payment
from app.models.user import User
from app.repositories import payment_repository as repo
from app.services import fee_situation
from app.services._school_settings_helper import (
    load_school_settings_for_pdf as _get_school_settings,
)
from app.services.payments._response import student_identity
from app.services.pdf._helpers import enum_value
from app.services.pdf_service import generate_receipt_pdf


def _fee_description(payment: Payment) -> str:
    """Compose la description courte du versement (1 ligne en-tête PDF)."""
    if payment.enrollment_fee and payment.enrollment_fee.fee_variant:
        cat = payment.enrollment_fee.fee_variant.category
        if cat:
            return cat.name
    allocations = payment.allocations or []
    if not allocations:
        if payment.enrollment_id is None:
            # La répartition par frais est partie avec l'inscription. Le
            # montant, lui, a bien été encaissé : le reçu doit le dire au
            # lieu de laisser la ligne « Nature » vide.
            return "Versement encaissé — dossier élève supprimé"
        return ""
    if len(allocations) == 1:
        ef = allocations[0].enrollment_fee
        if ef and ef.fee_variant and ef.fee_variant.category:
            return ef.fee_variant.category.name
    return f"Réparti sur {len(allocations)} frais par priorité"


async def _resolve_received_by_name(db: AsyncSession, user_id: int | None) -> str:
    """Affiche un nom user lisible (email avant @) ou vide."""
    if not user_id:
        return ""
    user_stmt = select(User).where(User.id == user_id)
    user_result = await db.execute(user_stmt)
    user = user_result.scalar_one_or_none()
    return user.email.split("@")[0] if user else ""


async def _build_situation(db: AsyncSession, enrollment_id: int | None) -> dict:
    """Projette la situation financière de l'inscription pour le PDF.

    Une inscription supprimée ne laisse plus de frais à totaliser : on rend un
    tableau vide plutôt qu'une erreur. Le reçu reste imprimable — c'est même
    tout ce qui atteste encore l'encaissement.
    """
    if enrollment_id is None:
        return {
            "lines": [],
            "total_due": Decimal("0"),
            "total_paid": Decimal("0"),
            "total_remaining": Decimal("0"),
        }

    situation = await fee_situation.load_situation(db, enrollment_id)
    return {
        "lines": [
            {
                "name": line.category_name,
                "due": line.due,
                "paid": line.paid,
                "remaining": line.remaining,
                "status": line.status,
            }
            for line in situation.lines
        ],
        "total_due": situation.total_due,
        "total_paid": situation.total_paid,
        "total_remaining": situation.total_remaining,
    }


async def _build_schedule(db: AsyncSession, enrollment_id: int | None) -> dict:
    """Prochaine échéance et retard éventuel, tels que l'échéancier les voit.

    L'échéancier dépend de tables optionnelles (grille de l'année, accord
    négocié). Quand il n'est pas configuré, il n'y a pas d'échéance à annoncer
    et le reçu n'en invente pas : la ligne disparaît, le reste du document
    tient sans elle.
    """
    if enrollment_id is None:
        return {}
    from app.services.installments import resolve_schedule

    schedule = await resolve_schedule(db, enrollment_id)
    return {
        "is_late": schedule.is_late,
        "late_amount": Decimal(str(schedule.late_amount)),
        "next_due_date": schedule.next_due_date,
        "next_due_amount": (
            Decimal(str(schedule.next_due_amount)) if schedule.next_due_amount is not None else None
        ),
    }


async def get_payment_receipt_pdf(db: AsyncSession, payment_id: int) -> bytes:
    """Génère le reçu d'un versement : une A4, deux exemplaires à découper.

    Chaque moitié porte le versement du jour et la situation financière
    complète de l'élève, pour que la famille reparte avec un document qui se
    suffit à lui-même.
    """
    payment = await repo.get_payment_with_allocations(db, payment_id)
    if payment is None:
        raise NotFoundError("Payment", payment_id)

    # Même résolution que la liste des versements : l'élève vivant d'abord,
    # l'identité figée ensuite. Un reçu réimprimé après la suppression d'une
    # fiche doit rester opposable, donc porter un nom.
    student_name, student_matricule, _photo, _supprime = student_identity(payment)
    if student_matricule:
        student_name = f"{student_name} ({student_matricule})"

    enrollment = payment.enrollment
    klass = getattr(enrollment, "class_", None) if enrollment is not None else None
    year = getattr(enrollment, "academic_year", None) if enrollment is not None else None

    school = await _get_school_settings(db)
    payment_data = {
        "payment_id": payment.id,
        "amount": payment.amount,
        # `enum_value` : SQLAlchemy rend l'objet enum, dont le `str()` donne
        # « PaymentMethod.CASH ». Le PDF a besoin de la valeur brute.
        "method": enum_value(payment.method),
        "reference": payment.reference,
        "status": enum_value(payment.status),
        "notes": payment.notes,
        "student_name": student_name or "",
        "class_name": getattr(klass, "name", "") or "",
        "academic_year_name": getattr(year, "name", "") or "",
        "fee_description": _fee_description(payment),
        "created_at": payment.created_at,
        "received_by_name": await _resolve_received_by_name(db, payment.received_by),
        "situation": await _build_situation(db, payment.enrollment_id),
        "schedule": await _build_schedule(db, payment.enrollment_id),
    }

    return generate_receipt_pdf(payment_data, school)
