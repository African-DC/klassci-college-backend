"""Service : composition + génération de l'état des frais individuel (PDF).

Compose le dict `data` attendu par `pdf.fee_statement.generate_fee_statement_pdf`
depuis l'ORM (Enrollment + EnrollmentFee + Payment + PaymentAllocation),
et délègue le rendu au générateur PDF stateless.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import NotFoundError
from app.models.academic import Class
from app.models.enrollment import Enrollment
from app.models.fee import EnrollmentFee, FeeVariant
from app.models.user import Student
from app.repositories import payment_repository as repo
from app.services import fee_situation, fees_paid
from app.services._school_settings_helper import (
    load_school_settings_for_pdf as _get_school_settings,
)
from app.services.pdf import generate_fee_statement_pdf
from app.services.pdf._helpers import enum_value


async def _load_enrollment_context(db: AsyncSession, enrollment_id: int) -> Enrollment:
    """Charge l'inscription avec student + class + academic_year + fees.

    Selectinload exhaustif pour éviter MissingGreenlet pendant la compose.
    """
    stmt = (
        select(Enrollment)
        .where(Enrollment.id == enrollment_id)
        .options(
            selectinload(Enrollment.student),
            selectinload(Enrollment.class_).selectinload(Class.level),
            selectinload(Enrollment.academic_year),
            selectinload(Enrollment.enrollment_fees)
            .selectinload(EnrollmentFee.fee_variant)
            .selectinload(FeeVariant.category),
        )
    )
    result = await db.execute(stmt)
    enrollment = result.scalar_one_or_none()
    if enrollment is None:
        raise NotFoundError("Enrollment", enrollment_id)
    return enrollment


def _student_full_name(student: Student) -> str:
    parts = [student.first_name or "", student.last_name or ""]
    return " ".join(p for p in parts if p).strip()


async def _build_fees_section(
    db: AsyncSession, enrollment: Enrollment
) -> tuple[list[dict], Decimal, Decimal]:
    """Compose les rows fees + retourne total_expected & total_paid.

    Le tri, la soustraction et les totaux vivent dans `fee_situation`, partagé
    avec le reçu de versement : l'état des frais et le reçu que la famille
    emporte ne peuvent pas annoncer deux restes à payer différents.

    Une requête groupée pour toute l'inscription, pas une par frais.
    """
    deja_verse = await fees_paid.paid_by_enrollment(db, enrollment.id)
    situation = fee_situation.situation_from_fees(enrollment.enrollment_fees or [], deja_verse)

    rows = [
        {
            "category_name": line.category_name,
            # L'etat des frais est la piece que la famille garde : il doit dire
            # ce que chaque ligne achete, pas seulement ce qu'elle coute.
            "entitlements": line.entitlements,
            "amount": line.due,
            "paid": line.paid,
            "remaining": line.remaining,
            "status": line.status,
        }
        for line in situation.lines
    ]
    return rows, situation.total_due, situation.total_paid


async def _build_payments_section(db: AsyncSession, enrollment_id: int) -> list[dict]:
    """Compose l'historique des versements (Payment.enrollment_id direct)."""
    payments = await repo.get_payments_by_enrollment_id(db, enrollment_id)
    rows: list[dict] = []
    for p in payments:
        rows.append(
            {
                "id": p.id,
                "created_at": p.created_at,
                "method": enum_value(p.method),
                "reference": p.reference,
                "amount": p.amount,
                "status": enum_value(p.status),
            }
        )
    return rows


async def get_fee_statement_pdf(db: AsyncSession, enrollment_id: int) -> bytes:
    """Génère et retourne l'état des frais en PDF pour une inscription."""
    enrollment = await _load_enrollment_context(db, enrollment_id)

    fees_rows, total_expected, total_paid = await _build_fees_section(db, enrollment)
    payments_rows = await _build_payments_section(db, enrollment_id)

    total_remaining = max(total_expected - total_paid, Decimal("0"))
    completion_rate = float(total_paid / total_expected * 100) if total_expected > 0 else 0.0

    student = enrollment.student
    klass = enrollment.class_
    ay = enrollment.academic_year

    data = {
        "student_name": _student_full_name(student) if student else "",
        "class_name": getattr(klass, "name", "") if klass else "",
        "academic_year_name": getattr(ay, "name", "") if ay else "",
        "enrollment_id": enrollment.id,
        "fees": fees_rows,
        "payments": payments_rows,
        "totals": {
            "total_expected": total_expected,
            "total_paid": total_paid,
            "total_remaining": total_remaining,
            "completion_rate": completion_rate,
        },
        "issued_at": datetime.utcnow(),
    }
    school = await _get_school_settings(db)
    return generate_fee_statement_pdf(data, school)
