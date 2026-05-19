"""Repository — accès DB pour TeacherSessionAttendance (Phase 7b)."""

from __future__ import annotations

from datetime import date as date_type
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.academic import AcademicYear
from app.models.attendance import TeacherAttendanceStatus, TeacherSessionAttendance
from app.models.timetable import TimetableSlot
from app.models.user import User

# ---------------------------------------------------------------------------
# Read — selectinload exhaustif (preload-relations-after-commit rule)
# ---------------------------------------------------------------------------


def _full_load_options() -> list[Any]:
    """Chaîne selectinload utilisée par tout GET retournant un response Pydantic."""
    return [
        selectinload(TeacherSessionAttendance.teacher),
        selectinload(TeacherSessionAttendance.slot).selectinload(TimetableSlot.subject),
        selectinload(TeacherSessionAttendance.slot).selectinload(TimetableSlot.class_),
        selectinload(TeacherSessionAttendance.academic_year),
        selectinload(TeacherSessionAttendance.declared_by),
        selectinload(TeacherSessionAttendance.validated_by),
    ]


async def get_by_id(db: AsyncSession, attendance_id: int) -> TeacherSessionAttendance | None:
    stmt = (
        select(TeacherSessionAttendance)
        .where(TeacherSessionAttendance.id == attendance_id)
        .options(*_full_load_options())
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def list_by_teacher(
    db: AsyncSession,
    teacher_id: int,
    academic_year_id: int | None = None,
    status: str | None = None,
    date_from: date_type | None = None,
    date_to: date_type | None = None,
    page: int = 1,
    per_page: int = 50,
) -> tuple[list[TeacherSessionAttendance], int]:
    """Liste paginée filtrée."""
    conditions = [TeacherSessionAttendance.teacher_id == teacher_id]
    if academic_year_id is not None:
        conditions.append(TeacherSessionAttendance.academic_year_id == academic_year_id)
    if status is not None:
        conditions.append(TeacherSessionAttendance.status == status)
    if date_from is not None:
        conditions.append(TeacherSessionAttendance.date >= date_from)
    if date_to is not None:
        conditions.append(TeacherSessionAttendance.date <= date_to)

    base_stmt = select(TeacherSessionAttendance).where(and_(*conditions))

    count_stmt = select(func.count()).select_from(base_stmt.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0

    list_stmt = (
        base_stmt.options(*_full_load_options())
        .order_by(TeacherSessionAttendance.date.desc(), TeacherSessionAttendance.id.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    result = await db.execute(list_stmt)
    return list(result.scalars().all()), total


# ---------------------------------------------------------------------------
# Stats agrégées (utilisé par GET /admin/teachers/{id}/attendance/stats)
# ---------------------------------------------------------------------------


async def count_by_status(
    db: AsyncSession,
    teacher_id: int,
    academic_year_id: int,
) -> dict[str, int]:
    """Compte par status pour l'AY donnée. Retourne dict status → count."""
    stmt = (
        select(TeacherSessionAttendance.status, func.count())
        .where(
            TeacherSessionAttendance.teacher_id == teacher_id,
            TeacherSessionAttendance.academic_year_id == academic_year_id,
            TeacherSessionAttendance.is_validated.is_(True),
        )
        .group_by(TeacherSessionAttendance.status)
    )
    result = await db.execute(stmt)
    return {row[0]: row[1] for row in result.all()}


async def sum_late_minutes(
    db: AsyncSession,
    teacher_id: int,
    academic_year_id: int,
) -> int:
    """Total minutes de retard cumulées pour l'AY (statuts LATE validés)."""
    stmt = select(func.coalesce(func.sum(TeacherSessionAttendance.late_minutes), 0)).where(
        TeacherSessionAttendance.teacher_id == teacher_id,
        TeacherSessionAttendance.academic_year_id == academic_year_id,
        TeacherSessionAttendance.status == TeacherAttendanceStatus.LATE,
        TeacherSessionAttendance.is_validated.is_(True),
    )
    result = await db.execute(stmt)
    return int(result.scalar() or 0)


async def count_pending_validation(
    db: AsyncSession,
    teacher_id: int,
) -> int:
    """Auto-déclarations en attente de validation admin."""
    stmt = select(func.count()).where(
        TeacherSessionAttendance.teacher_id == teacher_id,
        TeacherSessionAttendance.is_validated.is_(False),
    )
    result = await db.execute(stmt)
    return int(result.scalar() or 0)


# ---------------------------------------------------------------------------
# Slot ownership check (prevent admin from declaring on a slot that does
# not belong to the teacher — sloppy admin protection).
# ---------------------------------------------------------------------------


async def slot_belongs_to_teacher(db: AsyncSession, slot_id: int, teacher_id: int) -> bool:
    stmt = select(TimetableSlot.id).where(
        TimetableSlot.id == slot_id,
        TimetableSlot.teacher_id == teacher_id,
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none() is not None


# ---------------------------------------------------------------------------
# Unique constraint helper (1 row par teacher+slot+date)
# ---------------------------------------------------------------------------


async def exists_for(
    db: AsyncSession, teacher_id: int, slot_id: int | None, the_date: date_type
) -> TeacherSessionAttendance | None:
    """Retourne la row existante (teacher, slot, date) si présente. Sinon None.

    Pour `slot_id IS NULL` (absence hors EDT), on accepte plusieurs rows par
    teacher+date (réunion + congé maladie sur même jour possible).
    """
    if slot_id is None:
        return None  # pas d'unicité sans slot
    stmt = select(TeacherSessionAttendance).where(
        TeacherSessionAttendance.teacher_id == teacher_id,
        TeacherSessionAttendance.slot_id == slot_id,
        TeacherSessionAttendance.date == the_date,
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Current AY helper
# ---------------------------------------------------------------------------


async def get_current_academic_year(db: AsyncSession) -> AcademicYear | None:
    stmt = select(AcademicYear).where(AcademicYear.is_current.is_(True)).limit(1)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Count théorique des sessions EDT (pour `attendance_rate` denominator)
# ---------------------------------------------------------------------------


async def count_user_id_for_teacher(db: AsyncSession, teacher_id: int) -> int | None:
    """Helper : retourne le user_id du teacher (pour permissions / audit)."""
    from app.models.user import TeacherProfile

    stmt = select(TeacherProfile.user_id).where(TeacherProfile.id == teacher_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_user_by_id(db: AsyncSession, user_id: int) -> User | None:
    """Helper : récupère un user (pour audit_log + email dans response)."""
    stmt = select(User).where(User.id == user_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()
