"""Repository portail parent — accès DB lecture seule pour les données enfants."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.enrollment import Enrollment, EnrollmentStatus
from app.models.fee import EnrollmentFee, FeeVariant
from app.models.grade import Bulletin, Evaluation, Grade
from app.models.user import Parent, ParentStudent, Student


async def get_parent_by_user_id(db: AsyncSession, user_id: int) -> Parent | None:
    """Retourne le profil parent lié à un user_id."""
    stmt = select(Parent).where(Parent.user_id == user_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_parent_student_link(
    db: AsyncSession, parent_id: int, student_id: int
) -> ParentStudent | None:
    """Vérifie le lien parent-enfant."""
    stmt = select(ParentStudent).where(
        ParentStudent.parent_id == parent_id,
        ParentStudent.student_id == student_id,
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def list_children(db: AsyncSession, parent_id: int) -> list[ParentStudent]:
    """Retourne les liens parent-enfant avec les étudiants et leur inscription active."""
    stmt = (
        select(ParentStudent)
        .where(ParentStudent.parent_id == parent_id)
        .options(
            selectinload(ParentStudent.student)
            .selectinload(Student.enrollments)
            .selectinload(Enrollment.class_),
            selectinload(ParentStudent.student)
            .selectinload(Student.enrollments)
            .selectinload(Enrollment.academic_year),
        )
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_student_grades(
    db: AsyncSession, student_id: int, trimester: int | None = None
) -> list[Grade]:
    """Retourne les notes d'un élève avec détails évaluation."""
    stmt = (
        select(Grade)
        .where(Grade.student_id == student_id)
        .options(
            selectinload(Grade.evaluation).selectinload(Evaluation.subject),
        )
    )
    if trimester is not None:
        stmt = stmt.join(Grade.evaluation).where(Evaluation.trimester == trimester)
    stmt = stmt.order_by(Grade.id.desc())
    result = await db.execute(stmt)
    return list(result.scalars().unique().all())


async def get_student_active_enrollment(db: AsyncSession, student_id: int) -> Enrollment | None:
    """Retourne l'inscription active d'un élève avec ses frais et paiements."""
    stmt = (
        select(Enrollment)
        .where(
            Enrollment.student_id == student_id,
            Enrollment.status.not_in([EnrollmentStatus.ANNULE, EnrollmentStatus.REJETE]),
        )
        .options(
            selectinload(Enrollment.class_),
            selectinload(Enrollment.academic_year),
            selectinload(Enrollment.enrollment_fees)
            .selectinload(EnrollmentFee.fee_variant)
            .selectinload(FeeVariant.category),
            # Pas de `EnrollmentFee.payments` ici : la relation est dépréciée
            # depuis la migration 0028 et plus personne ne la lit. Le détail
            # des versements passe par `fees_paid.payments_by_enrollment_fee`.
        )
        .order_by(Enrollment.id.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_student_bulletins(db: AsyncSession, student_id: int) -> list[Bulletin]:
    """Retourne les bulletins publiés d'un élève."""
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
        .order_by(Bulletin.trimester.desc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())
