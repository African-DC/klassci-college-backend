"""Repository presences — acces DB pour AttendanceContext et AttendanceRecord."""

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.academic import AcademicYear
from app.models.attendance import AttendanceContext, AttendanceRecord
from app.models.user import Student


async def get_session_by_id(db: AsyncSession, session_id: int) -> AttendanceContext | None:
    """Retourne une session de pointage par ID avec ses records charges."""
    stmt = (
        select(AttendanceContext)
        .where(AttendanceContext.id == session_id)
        .options(selectinload(AttendanceContext.records))
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_academic_year_by_id(db: AsyncSession, academic_year_id: int) -> AcademicYear | None:
    """Retourne une annee scolaire par ID."""
    stmt = select(AcademicYear).where(AcademicYear.id == academic_year_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def create_context(
    db: AsyncSession,
    *,
    entity_type: str,
    context_id: int,
    date_val: date,
    academic_year_id: int,
) -> AttendanceContext:
    """Cree un AttendanceContext et flush pour obtenir l'ID."""
    context = AttendanceContext(
        entity_type=entity_type,
        context_id=context_id,
        date=date_val,
        academic_year_id=academic_year_id,
    )
    db.add(context)
    await db.flush()
    return context


async def create_record(
    db: AsyncSession,
    *,
    context_id: int,
    student_id: int,
    status: str,
    time_in: object = None,
    source: str = "manual",
    notes: str | None = None,
) -> AttendanceRecord:
    """Cree un AttendanceRecord et flush."""
    record = AttendanceRecord(
        context_id=context_id,
        student_id=student_id,
        status=status,
        time_in=time_in,
        source=source,
        notes=notes,
    )
    db.add(record)
    await db.flush()
    return record


async def get_record_by_context_and_student(
    db: AsyncSession, context_id: int, student_id: int
) -> AttendanceRecord | None:
    """Retourne un record pour un contexte et un eleve donnes."""
    stmt = select(AttendanceRecord).where(
        AttendanceRecord.context_id == context_id,
        AttendanceRecord.student_id == student_id,
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def update_record(
    db: AsyncSession,
    record: AttendanceRecord,
    *,
    status: str,
    time_in: object = None,
    notes: str | None = None,
) -> AttendanceRecord:
    """Met a jour un record de presence."""
    record.status = status
    if time_in is not None:
        record.time_in = time_in
    if notes is not None:
        record.notes = notes
    await db.flush()
    return record


async def list_records_for_student(
    db: AsyncSession,
    student_id: int,
    *,
    status: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = 1,
    size: int = 20,
) -> tuple[list[AttendanceRecord], int]:
    """Retourne les records de presence pour un eleve avec pagination."""
    base = (
        select(AttendanceRecord)
        .join(AttendanceContext, AttendanceRecord.context_id == AttendanceContext.id)
        .where(AttendanceRecord.student_id == student_id)
    )

    if status is not None:
        base = base.where(AttendanceRecord.status == status)
    if date_from is not None:
        base = base.where(AttendanceContext.date >= date_from)
    if date_to is not None:
        base = base.where(AttendanceContext.date <= date_to)

    count_stmt = select(func.count()).select_from(base.subquery())
    total: int = (await db.execute(count_stmt)).scalar() or 0

    stmt = base.offset((page - 1) * size).limit(size).order_by(AttendanceRecord.id.desc())
    rows = (await db.execute(stmt)).scalars().all()
    return list(rows), total


async def get_class_sessions(
    db: AsyncSession,
    class_id: int,
    *,
    academic_year_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[AttendanceContext]:
    """Retourne les sessions de pointage pour une classe."""
    base = (
        select(AttendanceContext)
        .where(
            AttendanceContext.entity_type == "class",
            AttendanceContext.context_id == class_id,
        )
        .options(selectinload(AttendanceContext.records))
    )

    if academic_year_id is not None:
        base = base.where(AttendanceContext.academic_year_id == academic_year_id)
    if date_from is not None:
        base = base.where(AttendanceContext.date >= date_from)
    if date_to is not None:
        base = base.where(AttendanceContext.date <= date_to)

    result = await db.execute(base.order_by(AttendanceContext.date.desc()))
    return list(result.scalars().all())


async def get_students_for_class_stats(
    db: AsyncSession, student_ids: set[int]
) -> dict[int, Student]:
    """Retourne les objets Student pour un ensemble d'IDs."""
    if not student_ids:
        return {}
    stmt = select(Student).where(Student.id.in_(student_ids))
    result = await db.execute(stmt)
    students = result.scalars().all()
    return {s.id: s for s in students}
