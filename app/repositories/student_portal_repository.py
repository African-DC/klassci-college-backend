"""Repository portail eleve — requetes DB read-only scopees par student."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.enrollment import Enrollment, EnrollmentStatus
from app.models.fee import EnrollmentFee, FeeVariant
from app.models.grade import Bulletin, Evaluation, Grade
from app.models.timetable import TimetableSlot
from app.models.user import Student


async def get_student_by_user_id(db: AsyncSession, user_id: int) -> Student | None:
    """Retourne le profil eleve lie a un user_id."""
    stmt = select(Student).where(Student.user_id == user_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_active_enrollment_for_student(db: AsyncSession, student_id: int) -> Enrollment | None:
    """Retourne l'inscription active (non annulee/rejetee) la plus recente."""
    stmt = (
        select(Enrollment)
        .where(
            Enrollment.student_id == student_id,
            Enrollment.status.not_in([EnrollmentStatus.ANNULE, EnrollmentStatus.REJETE]),
        )
        .options(
            selectinload(Enrollment.class_),
            selectinload(Enrollment.academic_year),
        )
        .order_by(Enrollment.id.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_grades_for_student(
    db: AsyncSession,
    student_id: int,
    *,
    trimester: int | None = None,
    subject_id: int | None = None,
) -> list[Grade]:
    """Retourne les notes d'un eleve avec details evaluation et matiere."""
    stmt = (
        select(Grade)
        .join(Grade.evaluation)
        .where(Grade.student_id == student_id)
        .options(
            selectinload(Grade.evaluation).selectinload(Evaluation.subject),
        )
    )
    if trimester is not None:
        stmt = stmt.where(Evaluation.trimester == trimester)
    if subject_id is not None:
        stmt = stmt.where(Evaluation.subject_id == subject_id)

    stmt = stmt.order_by(Evaluation.date.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_timetable_slots_for_class(db: AsyncSession, class_id: int) -> list[TimetableSlot]:
    """Retourne les creneaux emploi du temps d'une classe."""
    stmt = (
        select(TimetableSlot)
        .where(TimetableSlot.class_id == class_id)
        .options(
            selectinload(TimetableSlot.subject),
            selectinload(TimetableSlot.teacher),
            selectinload(TimetableSlot.room),
        )
        .order_by(TimetableSlot.day, TimetableSlot.start_time)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_enrollment_fees_for_enrollment(
    db: AsyncSession, enrollment_id: int
) -> list[EnrollmentFee]:
    """Retourne les frais d'une inscription avec paiements et categorie."""
    stmt = (
        select(EnrollmentFee)
        .where(EnrollmentFee.enrollment_id == enrollment_id)
        .options(
            selectinload(EnrollmentFee.payments),
            selectinload(EnrollmentFee.fee_variant).selectinload(FeeVariant.category),
        )
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_published_bulletins_for_student(db: AsyncSession, student_id: int) -> list[Bulletin]:
    """Retourne les bulletins publies d'un eleve."""
    stmt = (
        select(Bulletin)
        .where(
            Bulletin.student_id == student_id,
            Bulletin.is_published.is_(True),
        )
        .options(
            selectinload(Bulletin.class_),
            selectinload(Bulletin.academic_year),
        )
        .order_by(Bulletin.academic_year_id.desc(), Bulletin.trimester.desc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())
