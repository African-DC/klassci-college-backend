"""Repository — agrégations DB pour le score de performance.

Toutes les requêtes sont *groupées* (une passe pour tous les enseignants /
tout le personnel) pour éviter le N+1 : le service compose ensuite les scores
en mémoire. Aucune écriture ici — feature strictement read-only.
"""

from __future__ import annotations

from datetime import date as date_type
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.audit import AuditAction, AuditLog
from app.models.academic import AcademicYear
from app.models.attendance import (
    AttendanceContext,
    TeacherAttendanceStatus,
    TeacherSessionAttendance,
)
from app.models.enrollment import Enrollment
from app.models.fee import Payment, PaymentStatus
from app.models.grade import COUNTED_GRADE_STATUSES, Evaluation, Grade
from app.models.timetable import TimetableSlot
from app.models.user import StaffProfile, TeacherProfile

# ---------------------------------------------------------------------------
# Année scolaire courante (avec calendrier pour l'axe « appel »)
# ---------------------------------------------------------------------------


async def get_current_year_with_calendar(db: AsyncSession) -> AcademicYear | None:
    """AY courante + trimestres + congés préchargés (projection des séances)."""
    stmt = (
        select(AcademicYear)
        .where(AcademicYear.is_current.is_(True))
        .options(
            selectinload(AcademicYear.trimesters),
            selectinload(AcademicYear.holidays),
        )
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


# ---------------------------------------------------------------------------
# Acteurs
# ---------------------------------------------------------------------------


async def list_teachers(db: AsyncSession) -> list[TeacherProfile]:
    stmt = select(TeacherProfile).order_by(TeacherProfile.last_name, TeacherProfile.first_name)
    return list((await db.execute(stmt)).scalars().all())


async def get_teacher_by_user_id(db: AsyncSession, user_id: int) -> TeacherProfile | None:
    stmt = select(TeacherProfile).where(TeacherProfile.user_id == user_id)
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_staff(db: AsyncSession) -> list[StaffProfile]:
    stmt = (
        select(StaffProfile)
        .options(selectinload(StaffProfile.user))
        .order_by(StaffProfile.last_name, StaffProfile.first_name)
    )
    return list((await db.execute(stmt)).scalars().all())


# ---------------------------------------------------------------------------
# Axe 1 — Assiduité (pointage enseignant)
# ---------------------------------------------------------------------------


async def assiduite_counts_by_teacher(
    db: AsyncSession, academic_year_id: int
) -> dict[int, dict[str, int]]:
    """teacher_id → {status: count} sur les pointages validés de l'AY."""
    stmt = (
        select(
            TeacherSessionAttendance.teacher_id,
            TeacherSessionAttendance.status,
            func.count(),
        )
        .where(
            TeacherSessionAttendance.academic_year_id == academic_year_id,
            TeacherSessionAttendance.is_validated.is_(True),
        )
        .group_by(TeacherSessionAttendance.teacher_id, TeacherSessionAttendance.status)
    )
    result: dict[int, dict[str, int]] = {}
    for teacher_id, status, count in (await db.execute(stmt)).all():
        status_key = status.value if hasattr(status, "value") else str(status)
        result.setdefault(teacher_id, {})[status_key] = int(count)
    return result


async def late_minutes_by_teacher(db: AsyncSession, academic_year_id: int) -> dict[int, int]:
    stmt = (
        select(
            TeacherSessionAttendance.teacher_id,
            func.coalesce(func.sum(TeacherSessionAttendance.late_minutes), 0),
        )
        .where(
            TeacherSessionAttendance.academic_year_id == academic_year_id,
            TeacherSessionAttendance.status == TeacherAttendanceStatus.LATE,
            TeacherSessionAttendance.is_validated.is_(True),
        )
        .group_by(TeacherSessionAttendance.teacher_id)
    )
    return {teacher_id: int(total) for teacher_id, total in (await db.execute(stmt)).all()}


async def pending_validation_by_teacher(db: AsyncSession) -> dict[int, int]:
    stmt = (
        select(TeacherSessionAttendance.teacher_id, func.count())
        .where(TeacherSessionAttendance.is_validated.is_(False))
        .group_by(TeacherSessionAttendance.teacher_id)
    )
    return {teacher_id: int(count) for teacher_id, count in (await db.execute(stmt)).all()}


# ---------------------------------------------------------------------------
# Axe 2 — Saisie des notes
# ---------------------------------------------------------------------------


async def evaluations_for_year(
    db: AsyncSession, academic_year_id: int
) -> list[tuple[int, int, int]]:
    """(teacher_id, evaluation_id, class_id) pour l'AY."""
    stmt = select(Evaluation.teacher_id, Evaluation.id, Evaluation.class_id).where(
        Evaluation.academic_year_id == academic_year_id
    )
    return [(t, e, c) for t, e, c in (await db.execute(stmt)).all()]


async def enrolled_counts_by_class(db: AsyncSession, academic_year_id: int) -> dict[int, int]:
    stmt = (
        select(Enrollment.class_id, func.count())
        .where(
            Enrollment.academic_year_id == academic_year_id,
            Enrollment.status == "valide",
        )
        .group_by(Enrollment.class_id)
    )
    return {class_id: int(count) for class_id, count in (await db.execute(stmt)).all()}


async def entered_grades_by_evaluation(db: AsyncSession, academic_year_id: int) -> dict[int, int]:
    stmt = (
        select(Grade.evaluation_id, func.count())
        .join(Evaluation, Grade.evaluation_id == Evaluation.id)
        .where(
            Evaluation.academic_year_id == academic_year_id,
            # Marquer un élève absent est une saisie comme une autre : c'est
            # une case que l'enseignant a bien remplie.
            Grade.status.in_([s.value for s in COUNTED_GRADE_STATUSES]),
        )
        .group_by(Grade.evaluation_id)
    )
    return {eval_id: int(count) for eval_id, count in (await db.execute(stmt)).all()}


# ---------------------------------------------------------------------------
# Axe 3 — Prise de l'appel (attribution via audit_logs)
# ---------------------------------------------------------------------------


async def appels_taken_by_user(db: AsyncSession, academic_year_id: int) -> dict[int, int]:
    """user_id → nombre d'appels (contextes de présence) créés sur l'AY.

    L'appel élève ne porte pas de FK enseignant : l'auteur est tracé dans
    `audit_logs` (entity_type='attendance_session'). On joint sur le contexte
    pour scoper à l'année scolaire.
    """
    stmt = (
        select(AuditLog.user_id, func.count())
        .join(AttendanceContext, AuditLog.entity_id == AttendanceContext.id)
        .where(
            AuditLog.entity_type == "attendance_session",
            AuditLog.action == AuditAction.CREATE,
            AuditLog.user_id.isnot(None),
            AttendanceContext.academic_year_id == academic_year_id,
        )
        .group_by(AuditLog.user_id)
    )
    return {user_id: int(count) for user_id, count in (await db.execute(stmt)).all()}


async def teacher_slots_for_year(
    db: AsyncSession, academic_year_id: int
) -> list[tuple[int, str, int]]:
    """(teacher_id, day, class_id) — créneaux planifiés (séances attendues)."""
    stmt = select(TimetableSlot.teacher_id, TimetableSlot.day, TimetableSlot.class_id).where(
        TimetableSlot.academic_year_id == academic_year_id
    )
    rows = []
    for teacher_id, day, class_id in (await db.execute(stmt)).all():
        day_key = day.value if hasattr(day, "value") else str(day)
        rows.append((teacher_id, day_key, class_id))
    return rows


# ---------------------------------------------------------------------------
# Personnel — activité factuelle
# ---------------------------------------------------------------------------


async def payment_activity_by_user(
    db: AsyncSession, since: date_type
) -> dict[int, tuple[int, Decimal]]:
    """received_by → (nombre, montant total) des paiements encaissés depuis `since`."""
    stmt = (
        select(
            Payment.received_by,
            func.count(),
            func.coalesce(func.sum(Payment.amount), 0),
        )
        .where(
            Payment.received_by.isnot(None),
            Payment.status == PaymentStatus.COMPLETED,
            Payment.created_at >= since,
        )
        .group_by(Payment.received_by)
    )
    return {
        user_id: (int(count), Decimal(total))
        for user_id, count, total in (await db.execute(stmt)).all()
    }


async def enrollment_activity_by_user(db: AsyncSession, since: date_type) -> dict[int, int]:
    """created_by → nombre d'inscriptions traitées depuis `since`."""
    stmt = (
        select(Enrollment.created_by, func.count())
        .where(
            Enrollment.created_by.isnot(None),
            Enrollment.created_at >= since,
        )
        .group_by(Enrollment.created_by)
    )
    return {user_id: int(count) for user_id, count in (await db.execute(stmt)).all()}
