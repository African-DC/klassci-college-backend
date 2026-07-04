"""Repository conseil de classe — accès DB pour CouncilMinutes et CouncilStudentDecision."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.attendance import AttendanceContext, AttendanceRecord, AttendanceStatus
from app.models.enrollment import Enrollment
from app.models.grade import (
    Bulletin,
    CouncilMinutes,
    CouncilStudentDecision,
)
from app.models.user import Student

# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


async def get_council_minutes(
    db: AsyncSession,
    class_id: int,
    trimester: int,
    academic_year_id: int,
) -> CouncilMinutes | None:
    """Retourne le PV du conseil pour une classe/trimestre/année."""
    stmt = (
        select(CouncilMinutes)
        .where(
            CouncilMinutes.class_id == class_id,
            CouncilMinutes.trimester == trimester,
            CouncilMinutes.academic_year_id == academic_year_id,
        )
        .options(
            selectinload(CouncilMinutes.decisions).selectinload(CouncilStudentDecision.student),
            selectinload(CouncilMinutes.class_),
            selectinload(CouncilMinutes.academic_year),
        )
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_council_minutes_by_id(
    db: AsyncSession,
    council_id: int,
) -> CouncilMinutes | None:
    stmt = (
        select(CouncilMinutes)
        .where(CouncilMinutes.id == council_id)
        .options(
            selectinload(CouncilMinutes.decisions).selectinload(CouncilStudentDecision.student),
            selectinload(CouncilMinutes.class_),
            selectinload(CouncilMinutes.academic_year),
        )
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_decision_by_id(
    db: AsyncSession,
    decision_id: int,
) -> CouncilStudentDecision | None:
    stmt = select(CouncilStudentDecision).where(CouncilStudentDecision.id == decision_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------


async def get_enrolled_students(
    db: AsyncSession,
    class_id: int,
    academic_year_id: int,
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


async def get_bulletin_for_student(
    db: AsyncSession,
    student_id: int,
    class_id: int,
    academic_year_id: int,
    trimester: int,
) -> Bulletin | None:
    """Retourne le bulletin d'un eleve pour un trimestre."""
    stmt = select(Bulletin).where(
        Bulletin.student_id == student_id,
        Bulletin.class_id == class_id,
        Bulletin.academic_year_id == academic_year_id,
        Bulletin.trimester == trimester,
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def count_absences_for_student(
    db: AsyncSession,
    student_id: int,
    class_id: int,
    academic_year_id: int,
) -> int:
    """Compte les absences d'un eleve pour une classe/annee."""
    stmt = (
        select(func.count(AttendanceRecord.id))
        .join(AttendanceContext, AttendanceContext.id == AttendanceRecord.context_id)
        .where(
            AttendanceRecord.student_id == student_id,
            AttendanceRecord.status == AttendanceStatus.ABSENT.value,
            AttendanceContext.context_id == class_id,
            AttendanceContext.academic_year_id == academic_year_id,
        )
    )
    result = await db.execute(stmt)
    return result.scalar() or 0


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------


async def create_council_minutes(
    db: AsyncSession,
    *,
    class_id: int,
    academic_year_id: int,
    trimester: int,
    main_teacher_name: str | None = None,
    director_name: str | None = None,
    dren_name: str | None = None,
    notes: str | None = None,
) -> CouncilMinutes:
    """Cree le PV du conseil."""
    council = CouncilMinutes(
        class_id=class_id,
        academic_year_id=academic_year_id,
        trimester=trimester,
        main_teacher_name=main_teacher_name,
        director_name=director_name,
        dren_name=dren_name,
        notes=notes,
        generated_at=datetime.utcnow(),
        is_published=False,
    )
    db.add(council)
    await db.flush()
    return council


async def create_student_decision(
    db: AsyncSession,
    *,
    council_minutes_id: int,
    student_id: int,
    average: Decimal | None,
    rank: int | None,
    absence_count: int,
    auto_decision: str,
) -> CouncilStudentDecision:
    """Cree une decision pour un eleve."""
    decision = CouncilStudentDecision(
        council_minutes_id=council_minutes_id,
        student_id=student_id,
        average=average,
        rank=rank,
        absence_count=absence_count,
        auto_decision=auto_decision,
    )
    db.add(decision)
    await db.flush()
    return decision


async def update_decision_override(
    db: AsyncSession,
    decision: CouncilStudentDecision,
    final_decision: str,
    override_reason: str,
) -> CouncilStudentDecision:
    """Met a jour la decision du conseil pour un eleve."""
    decision.final_decision = final_decision
    decision.override_reason = override_reason
    await db.flush()
    return decision


async def set_published(
    db: AsyncSession,
    council: CouncilMinutes,
    is_published: bool,
) -> CouncilMinutes:
    """Marque le PV comme publie (valide) ou brouillon."""
    council.is_published = is_published
    await db.flush()
    return council


async def delete_council_minutes(
    db: AsyncSession,
    council: CouncilMinutes,
) -> None:
    """Supprime un PV et ses decisions (CASCADE)."""
    await db.delete(council)
    await db.flush()
