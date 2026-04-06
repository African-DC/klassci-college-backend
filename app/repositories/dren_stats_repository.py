"""Repository DREN stats — requêtes d'agrégation en lecture seule."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.academic import AcademicYear, Class, Level, Subject
from app.models.enrollment import Enrollment, EnrollmentStatus
from app.models.grade import Bulletin, Grade, Evaluation
from app.models.timetable import TimetableSlot
from app.models.user import Genre, Student


async def get_academic_year(db: AsyncSession, academic_year_id: int) -> AcademicYear | None:
    """Récupère une année scolaire par son ID."""
    stmt = select(AcademicYear).where(AcademicYear.id == academic_year_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_enrollment_counts_by_level(
    db: AsyncSession, academic_year_id: int
) -> list[tuple[int, str, int, int, int, int]]:
    """Effectifs par niveau avec répartition par genre.

    Returns list of (level_id, level_name, level_order, total, male, female).
    """
    stmt = (
        select(
            Level.id,
            Level.name,
            Level.order,
            func.count(Student.id).label("total"),
            func.count(case((Student.genre == Genre.M, 1))).label("male"),
            func.count(case((Student.genre == Genre.F, 1))).label("female"),
        )
        .join(Class, Class.level_id == Level.id)
        .join(Enrollment, Enrollment.class_id == Class.id)
        .join(Student, Student.id == Enrollment.student_id)
        .where(
            Class.academic_year_id == academic_year_id,
            Enrollment.status.in_([EnrollmentStatus.VALIDE, EnrollmentStatus.EN_VALIDATION]),
        )
        .group_by(Level.id, Level.name, Level.order)
        .order_by(Level.order)
    )
    result = await db.execute(stmt)
    return list(result.all())


async def get_enrollment_counts_by_class(
    db: AsyncSession, academic_year_id: int
) -> list[tuple[int, str, int, int, int, int, Decimal | None]]:
    """Effectifs par classe avec répartition par genre et moyenne de classe.

    Returns list of (class_id, class_name, level_id, total, male, female, class_avg).
    """
    # Subquery: average per class from bulletins (latest trimester available)
    bulletin_avg_sq = (
        select(
            Bulletin.class_id,
            func.avg(Bulletin.average).label("class_avg"),
        )
        .where(Bulletin.academic_year_id == academic_year_id, Bulletin.average.isnot(None))
        .group_by(Bulletin.class_id)
        .subquery()
    )

    stmt = (
        select(
            Class.id,
            Class.name,
            Class.level_id,
            func.count(Student.id).label("total"),
            func.count(case((Student.genre == Genre.M, 1))).label("male"),
            func.count(case((Student.genre == Genre.F, 1))).label("female"),
            bulletin_avg_sq.c.class_avg,
        )
        .join(Enrollment, Enrollment.class_id == Class.id)
        .join(Student, Student.id == Enrollment.student_id)
        .outerjoin(bulletin_avg_sq, bulletin_avg_sq.c.class_id == Class.id)
        .where(
            Class.academic_year_id == academic_year_id,
            Enrollment.status.in_([EnrollmentStatus.VALIDE, EnrollmentStatus.EN_VALIDATION]),
        )
        .group_by(Class.id, Class.name, Class.level_id, bulletin_avg_sq.c.class_avg)
        .order_by(Class.name)
    )
    result = await db.execute(stmt)
    return list(result.all())


async def get_bulletin_rates(
    db: AsyncSession, academic_year_id: int
) -> tuple[float | None, float | None, float | None, float | None]:
    """Taux de réussite, échec, redoublement et exclusion depuis les bulletins.

    Basé sur le trimestre le plus récent disponible.
    Réussite: average >= 10, Redoublement: 8.5 <= average < 10, Exclusion: average < 8.5.

    Returns (success_rate, failure_rate, redoublement_rate, exclusion_rate) as percentages.
    """
    # Find the latest trimester with bulletins
    latest_trimester_stmt = (
        select(func.max(Bulletin.trimester))
        .where(
            Bulletin.academic_year_id == academic_year_id,
            Bulletin.average.isnot(None),
        )
    )
    result = await db.execute(latest_trimester_stmt)
    latest_trimester = result.scalar_one_or_none()

    if latest_trimester is None:
        return None, None, None, None

    # Count bulletins by category
    stmt = select(
        func.count().label("total"),
        func.count(case((Bulletin.average >= 10, 1))).label("success"),
        func.count(
            case(
                (and_(Bulletin.average >= Decimal("8.5"), Bulletin.average < 10), 1),
            )
        ).label("redoublement"),
        func.count(case((Bulletin.average < Decimal("8.5"), 1))).label("exclusion"),
    ).where(
        Bulletin.academic_year_id == academic_year_id,
        Bulletin.trimester == latest_trimester,
        Bulletin.average.isnot(None),
    )
    result = await db.execute(stmt)
    row = result.one()

    total = row.total
    if total == 0:
        return None, None, None, None

    success_rate = round((row.success / total) * 100, 2)
    failure_rate = round(((total - row.success) / total) * 100, 2)
    redoublement_rate = round((row.redoublement / total) * 100, 2)
    exclusion_rate = round((row.exclusion / total) * 100, 2)

    return success_rate, failure_rate, redoublement_rate, exclusion_rate


async def get_subject_averages(
    db: AsyncSession, academic_year_id: int
) -> list[tuple[int, str, Decimal | None]]:
    """Moyennes générales par matière.

    Returns list of (subject_id, subject_name, overall_average).
    """
    stmt = (
        select(
            Subject.id,
            Subject.name,
            func.avg(Grade.value).label("overall_average"),
        )
        .join(Evaluation, Evaluation.subject_id == Subject.id)
        .join(Grade, Grade.evaluation_id == Evaluation.id)
        .where(
            Evaluation.academic_year_id == academic_year_id,
            Grade.value.isnot(None),
        )
        .group_by(Subject.id, Subject.name)
        .order_by(Subject.name)
    )
    result = await db.execute(stmt)
    return list(result.all())


async def get_teacher_counts_by_subject(
    db: AsyncSession, academic_year_id: int
) -> list[tuple[int, int]]:
    """Nombre d'enseignants distincts par matière.

    Returns list of (subject_id, teacher_count).
    """
    stmt = (
        select(
            TimetableSlot.subject_id,
            func.count(func.distinct(TimetableSlot.teacher_id)).label("teacher_count"),
        )
        .where(TimetableSlot.academic_year_id == academic_year_id)
        .group_by(TimetableSlot.subject_id)
    )
    result = await db.execute(stmt)
    return list(result.all())
