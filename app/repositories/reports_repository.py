"""Repository reports — accès DB pour Bulletin et SubjectAverage."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.enrollment import Enrollment
from app.models.grade import (
    Bulletin,
    Evaluation,
    Grade,
    GradeStatus,
    SubjectAverage,
)
from app.models.user import Student


async def get_enrolled_students(
    db: AsyncSession, class_id: int, academic_year_id: int
) -> list[Student]:
    """Retourne les eleves inscrits (valide) dans une classe."""
    stmt = (
        select(Student)
        .join(Enrollment, Enrollment.student_id == Student.id)
        .where(
            Enrollment.class_id == class_id,
            Enrollment.academic_year_id == academic_year_id,
            Enrollment.status == "valide",
        )
        .order_by(Student.last_name, Student.first_name)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_evaluations_for_class_trimester(
    db: AsyncSession,
    class_id: int,
    trimester: int,
    academic_year_id: int,
) -> list[Evaluation]:
    """Retourne toutes les evaluations d'une classe pour un trimestre."""
    stmt = (
        select(Evaluation)
        .where(
            Evaluation.class_id == class_id,
            Evaluation.trimester == trimester,
            Evaluation.academic_year_id == academic_year_id,
        )
        .options(selectinload(Evaluation.subject))
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_entered_grades_for_evaluations(db: AsyncSession, eval_ids: list[int]) -> list[Grade]:
    """Retourne toutes les notes saisies pour une liste d'evaluations."""
    if not eval_ids:
        return []
    stmt = select(Grade).where(
        Grade.evaluation_id.in_(eval_ids),
        Grade.status == GradeStatus.ENTERED,
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_bulletin(
    db: AsyncSession,
    student_id: int,
    class_id: int,
    academic_year_id: int,
    trimester: int,
) -> Bulletin | None:
    """Retourne un bulletin existant ou None."""
    stmt = select(Bulletin).where(
        Bulletin.student_id == student_id,
        Bulletin.class_id == class_id,
        Bulletin.academic_year_id == academic_year_id,
        Bulletin.trimester == trimester,
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def upsert_bulletin(
    db: AsyncSession,
    *,
    student_id: int,
    class_id: int,
    academic_year_id: int,
    trimester: int,
    average: Decimal | None,
    rank: int | None,
    mention: str | None,
    teacher_comment: str | None = None,
    council_decision: str | None = None,
) -> Bulletin:
    """Cree ou met a jour un bulletin."""
    bulletin = await get_bulletin(db, student_id, class_id, academic_year_id, trimester)

    if bulletin is None:
        bulletin = Bulletin(
            student_id=student_id,
            class_id=class_id,
            academic_year_id=academic_year_id,
            trimester=trimester,
            average=average,
            rank=rank,
            mention=mention,
            teacher_comment=teacher_comment,
            council_decision=council_decision,
        )
        db.add(bulletin)
    else:
        bulletin.average = average
        bulletin.rank = rank
        bulletin.mention = mention
        bulletin.teacher_comment = teacher_comment
        bulletin.council_decision = council_decision

    await db.flush()
    return bulletin


async def delete_subject_averages_for_bulletin(db: AsyncSession, bulletin_id: int) -> None:
    """Supprime les moyennes par matiere d'un bulletin (avant regeneration)."""
    stmt = delete(SubjectAverage).where(SubjectAverage.bulletin_id == bulletin_id)
    await db.execute(stmt)


async def create_subject_average(
    db: AsyncSession,
    *,
    bulletin_id: int,
    subject_id: int,
    student_id: int,
    trimester: int,
    average: Decimal,
    coefficient: int,
) -> SubjectAverage:
    """Cree une moyenne par matiere."""
    sa_record = SubjectAverage(
        bulletin_id=bulletin_id,
        subject_id=subject_id,
        student_id=student_id,
        trimester=trimester,
        average=average,
        coefficient=coefficient,
    )
    db.add(sa_record)
    await db.flush()
    return sa_record


async def list_bulletins(
    db: AsyncSession,
    *,
    class_id: int | None = None,
    trimester: int | None = None,
    academic_year_id: int | None = None,
    is_published: bool | None = None,
) -> list[Bulletin]:
    """Retourne les bulletins selon filtres optionnels."""
    stmt = (
        select(Bulletin)
        .options(
            selectinload(Bulletin.student),
            selectinload(Bulletin.class_),
            selectinload(Bulletin.subject_averages).selectinload(SubjectAverage.subject),
        )
        .order_by(
            Bulletin.academic_year_id.desc(),
            Bulletin.trimester.desc(),
            # MySQL doesn't support `NULLS LAST`. The `IS NULL` trick puts NULLs at
            # the end (booleans cast to 0=non-null, 1=null in ORDER BY context).
            Bulletin.rank.is_(None),
            Bulletin.rank.asc(),
        )
    )
    if class_id is not None:
        stmt = stmt.where(Bulletin.class_id == class_id)
    if trimester is not None:
        stmt = stmt.where(Bulletin.trimester == trimester)
    if academic_year_id is not None:
        stmt = stmt.where(Bulletin.academic_year_id == academic_year_id)
    if is_published is not None:
        stmt = stmt.where(Bulletin.is_published.is_(is_published))
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_bulletin_by_id(db: AsyncSession, bulletin_id: int) -> Bulletin | None:
    """Retourne un bulletin par ID avec ses relations.

    `academic_year` est explicitement selectinload pour éviter un lazy-load
    déclenché par `pdf_service.generate_bulletin_pdf` qui lit
    `bulletin.academic_year.name`. Sans ça : MissingGreenlet → 500 plain text
    sur GET /reports/bulletins/{id}/pdf.
    """
    stmt = (
        select(Bulletin)
        .where(Bulletin.id == bulletin_id)
        .options(
            selectinload(Bulletin.student),
            selectinload(Bulletin.class_),
            selectinload(Bulletin.academic_year),
            selectinload(Bulletin.subject_averages).selectinload(SubjectAverage.subject),
        )
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def count_enrolled_students(db: AsyncSession, class_id: int, academic_year_id: int) -> int:
    """Compte les eleves inscrits valides dans une classe."""
    stmt = (
        select(func.count())
        .select_from(Enrollment)
        .where(
            Enrollment.class_id == class_id,
            Enrollment.academic_year_id == academic_year_id,
            Enrollment.status == "valide",
        )
    )
    return (await db.execute(stmt)).scalar() or 0
