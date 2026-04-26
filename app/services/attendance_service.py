"""Service presences — logique metier CRUD + stats."""

import logging
from collections import defaultdict

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditAction, audit_log
from app.core.exceptions import BusinessValidationError, NotFoundError
from app.models.attendance import AttendanceStatus
from app.repositories import attendance_repository as repo
from app.schemas.attendance import (
    AttendanceRecordResponse,
    ClassAttendanceStats,
    SessionCreate,
    SessionResponse,
    SessionUpdate,
    StudentAttendanceResponse,
    StudentAttendanceSummary,
)

logger = logging.getLogger(__name__)

_VALID_STATUSES = {s.value for s in AttendanceStatus}


def _record_to_response(record: object) -> AttendanceRecordResponse:
    """Convertit un AttendanceRecord ORM en AttendanceRecordResponse."""
    return AttendanceRecordResponse.model_validate(record)


def _session_to_response(context: object) -> SessionResponse:
    """Convertit un AttendanceContext ORM en SessionResponse."""
    return SessionResponse.model_validate(context)


async def create_session(
    db: AsyncSession,
    data: SessionCreate,
    created_by: int,
) -> SessionResponse:
    """Cree une session de pointage avec les records pour tous les eleves."""
    # Valider que l'annee scolaire existe
    academic_year = await repo.get_academic_year_by_id(db, data.academic_year_id)
    if academic_year is None:
        raise BusinessValidationError(f"AcademicYear {data.academic_year_id} not found")

    async with db.begin_nested():
        # Creer le contexte
        context = await repo.create_context(
            db,
            entity_type=data.entity_type,
            context_id=data.context_id,
            date_val=data.date,
            academic_year_id=data.academic_year_id,
        )

        # Creer un record par eleve
        for rec in data.records:
            await repo.create_record(
                db,
                context_id=context.id,
                student_id=rec.student_id,
                status=rec.status,
                time_in=rec.time_in,
                notes=rec.notes,
            )

        await audit_log(
            db,
            entity_type="attendance_session",
            action=AuditAction.CREATE,
            user_id=created_by,
            entity_id=context.id,
            new_values=data.model_dump(mode="json"),
        )

    await db.commit()

    # After commit, notify absent students (best-effort)
    try:
        from sqlalchemy import select

        from app.models.notification import NotificationType
        from app.models.user import Student
        from app.services import notification_dispatch_service as notif

        for record in data.records:
            if record.status == "absent" and record.student_id:
                result = await db.execute(select(Student).where(Student.id == record.student_id))
                student_obj = result.scalar_one_or_none()
                if student_obj and student_obj.user_id:
                    await notif.dispatch_notification(
                        db,
                        user_id=student_obj.user_id,
                        notification_type=NotificationType.ABSENCE_RECORDED,
                        context={
                            "title": "Absence signalée",
                            "body": f"Une absence a été enregistrée le {data.date}.",
                        },
                    )
    except Exception:
        logger.exception("Failed to dispatch absence notifications")

    refreshed = await repo.get_session_by_id(db, context.id)
    if refreshed is None:
        raise NotFoundError("AttendanceSession", context.id)
    return _session_to_response(refreshed)


async def update_session(
    db: AsyncSession,
    session_id: int,
    data: SessionUpdate,
    updated_by: int,
) -> SessionResponse:
    """Met a jour les records d'une session de pointage."""
    context = await repo.get_session_by_id(db, session_id)
    if context is None:
        raise NotFoundError("AttendanceSession", session_id)

    # Capture old values for audit
    old_values = {r.student_id: r.status for r in context.records if hasattr(r, "student_id")}

    async with db.begin_nested():
        for rec_input in data.records:
            existing = await repo.get_record_by_context_and_student(
                db, session_id, rec_input.student_id
            )
            if existing is not None:
                await repo.update_record(
                    db,
                    existing,
                    status=rec_input.status,
                    time_in=rec_input.time_in,
                    notes=rec_input.notes,
                )
            else:
                # Student not in original session — add new record
                await repo.create_record(
                    db,
                    context_id=session_id,
                    student_id=rec_input.student_id,
                    status=rec_input.status,
                    time_in=rec_input.time_in,
                    notes=rec_input.notes,
                )

        new_values = {r.student_id: r.status for r in data.records}
        await audit_log(
            db,
            entity_type="attendance_session",
            action=AuditAction.UPDATE,
            user_id=updated_by,
            entity_id=session_id,
            old_values=old_values,
            new_values=new_values,
        )

    await db.commit()

    refreshed = await repo.get_session_by_id(db, session_id)
    if refreshed is None:
        raise NotFoundError("AttendanceSession", session_id)
    return _session_to_response(refreshed)


async def get_student_attendance(
    db: AsyncSession,
    student_id: int,
    *,
    status: str | None = None,
    date_from: object = None,
    date_to: object = None,
    page: int = 1,
    size: int = 20,
) -> StudentAttendanceResponse:
    """Retourne l'historique de presence d'un eleve avec pagination."""
    if status is not None and status not in _VALID_STATUSES:
        raise BusinessValidationError(f"Invalid status '{status}'. Valid: {_VALID_STATUSES}")

    records, total = await repo.list_records_for_student(
        db,
        student_id,
        status=status,
        date_from=date_from,
        date_to=date_to,
        page=page,
        size=size,
    )
    return StudentAttendanceResponse(
        items=[_record_to_response(r) for r in records],
        total=total,
        page=page,
        size=size,
    )


async def get_class_stats(
    db: AsyncSession,
    class_id: int,
    *,
    academic_year_id: int | None = None,
    date_from: object = None,
    date_to: object = None,
) -> ClassAttendanceStats:
    """Calcule les stats de presence pour une classe."""
    sessions = await repo.get_class_sessions(
        db,
        class_id,
        academic_year_id=academic_year_id,
        date_from=date_from,
        date_to=date_to,
    )

    total_sessions = len(sessions)

    # Aggregate per student
    student_counts: dict[int, dict[str, int]] = defaultdict(
        lambda: {"present": 0, "absent": 0, "late": 0, "excused": 0}
    )

    for session in sessions:
        for record in session.records:
            sid = record.student_id
            st = record.status if isinstance(record.status, str) else record.status.value
            if st in student_counts[sid]:
                student_counts[sid][st] += 1

    # Fetch student names
    student_ids = set(student_counts.keys())
    students_map = await repo.get_students_for_class_stats(db, student_ids)

    # Build summaries
    summaries: list[StudentAttendanceSummary] = []
    total_present_all = 0
    total_records_all = 0

    for sid, counts in student_counts.items():
        student = students_map.get(sid)
        first_name = student.first_name if student else "Unknown"
        last_name = student.last_name if student else "Unknown"

        total_for_student = sum(counts.values())
        present_equiv = counts["present"] + counts["late"]
        rate = (present_equiv / total_for_student * 100.0) if total_for_student > 0 else 0.0

        total_present_all += present_equiv
        total_records_all += total_for_student

        summaries.append(
            StudentAttendanceSummary(
                student_id=sid,
                first_name=first_name,
                last_name=last_name,
                present_count=counts["present"],
                absent_count=counts["absent"],
                late_count=counts["late"],
                excused_count=counts["excused"],
                attendance_rate=round(rate, 2),
            )
        )

    overall_rate = (total_present_all / total_records_all * 100.0) if total_records_all > 0 else 0.0

    return ClassAttendanceStats(
        class_id=class_id,
        total_sessions=total_sessions,
        attendance_rate=round(overall_rate, 2),
        students=summaries,
    )
