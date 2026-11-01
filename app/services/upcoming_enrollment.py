"""Ce qu'une famille doit déjà pour l'année qui vient, à côté de l'année en cours.

Les portails suivent l'année en cours. Une réinscription pour l'année suivante
reste pourtant de l'argent à régler : on la présente à part, sans la mêler au
total de l'année ni aux arriérés.
"""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.academic import AcademicYear
from app.models.enrollment import Enrollment, EnrollmentStatus
from app.models.fee import cash_remaining, is_not_cash_due
from app.schemas.upcoming_enrollment import UpcomingEnrollmentFees
from app.services import fees_paid


async def find_upcoming_enrollments(
    db: AsyncSession, *, student_id: int, in_force: Enrollment
) -> list[Enrollment]:
    """Les inscriptions ouvertes sur des années postérieures à celle affichée, la plus proche d'abord."""
    stmt = (
        select(Enrollment)
        .join(Enrollment.academic_year)
        .where(
            Enrollment.student_id == student_id,
            Enrollment.status.not_in([EnrollmentStatus.ANNULE, EnrollmentStatus.REJETE]),
            AcademicYear.start_date > in_force.academic_year.start_date,
        )
        .options(
            selectinload(Enrollment.class_),
            selectinload(Enrollment.academic_year),
            selectinload(Enrollment.enrollment_fees),
        )
        .order_by(AcademicYear.start_date, Enrollment.id.desc())
    )
    return list((await db.execute(stmt)).scalars().all())


async def summarize(
    db: AsyncSession, enrollment: Enrollment | None
) -> UpcomingEnrollmentFees | None:
    """Les totaux à afficher ; rien tant qu'aucun frais n'est dû en argent."""
    if enrollment is None:
        return None
    paid_by_fee = await fees_paid.paid_by_enrollment(db, enrollment.id)
    total_due = Decimal("0.00")
    total_paid = Decimal("0.00")
    remaining = Decimal("0.00")
    for fee in enrollment.enrollment_fees:
        paid = paid_by_fee.get(fee.id, Decimal("0"))
        remaining += cash_remaining(fee.status, fee.amount, paid)
        if not is_not_cash_due(fee.status):
            total_due += fee.amount
            total_paid += paid
    if total_due <= 0:
        return None
    return UpcomingEnrollmentFees(
        academic_year_name=enrollment.academic_year.name,
        class_name=enrollment.class_.name if enrollment.class_ else None,
        total_due=total_due,
        total_paid=total_paid,
        remaining=remaining,
    )
