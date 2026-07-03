"""Service portail enseignant — logique métier read-only."""

import logging
from datetime import date

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.user import TeacherProfile
from app.repositories import admin_repository, reports_repository
from app.repositories import teacher_portal_repository as repo
from app.schemas.attendance import ClassAttendanceStats
from app.schemas.teacher_portal import (
    TeacherClassesListResponse,
    TeacherClassResponse,
    TeacherClassRosterResponse,
    TeacherDashboardStats,
    TeacherNextCourse,
    TeacherRosterStudent,
    TeacherScheduleResponse,
    TeacherScheduleSlot,
    TeacherUpcomingEval,
)
from app.services import attendance_service

logger = logging.getLogger(__name__)


async def _get_teacher_for_user(db: AsyncSession, user_id: int) -> TeacherProfile:
    """Retourne le profil enseignant ou lève NotFoundError."""
    teacher = await repo.get_teacher_by_user_id(db, user_id)
    if teacher is None:
        raise NotFoundError("TeacherProfile", user_id)
    return teacher


async def get_classes(db: AsyncSession, user_id: int) -> TeacherClassesListResponse:
    """Retourne les classes assignées à l'enseignant via timetable_slots."""
    teacher = await _get_teacher_for_user(db, user_id)
    classes = await repo.get_teacher_classes(db, teacher.id)
    items = [TeacherClassResponse(**c) for c in classes]
    return TeacherClassesListResponse(items=items, total=len(items))


async def get_schedule(db: AsyncSession, user_id: int) -> TeacherScheduleResponse:
    """Retourne l'emploi du temps personnel de l'enseignant."""
    teacher = await _get_teacher_for_user(db, user_id)
    slots = await repo.get_teacher_schedule(db, teacher.id)
    items = [
        TeacherScheduleSlot(
            id=slot.id,
            day=slot.day,
            start_time=slot.start_time,
            end_time=slot.end_time,
            subject_name=slot.subject.name,
            class_name=slot.class_.name,
            room_name=slot.room.name if slot.room else None,
        )
        for slot in slots
    ]
    return TeacherScheduleResponse(items=items, total=len(items))


async def get_dashboard_stats(db: AsyncSession, user_id: int) -> TeacherDashboardStats:
    """Retourne le dashboard de l'enseignant connecté.

    Aligné sur le contrat FE `TeacherDashboardSchema` (lib/contracts/teacher-portal.ts) :
    nom, totaux, prochain cours, évaluations à venir/récentes.
    """
    teacher = await _get_teacher_for_user(db, user_id)

    total_classes = await repo.count_distinct_classes(db, teacher.id)
    total_students = await repo.count_total_students(db, teacher.id)
    next_course_raw = await repo.get_next_course(db, teacher.id)
    upcoming_raw = await repo.list_upcoming_evaluations(db, teacher.id, limit=5)
    current_ay_name = await admin_repository.get_current_academic_year_name(db)

    return TeacherDashboardStats(
        teacher_name=f"{teacher.first_name} {teacher.last_name}".strip(),
        total_classes=total_classes,
        total_students=total_students,
        next_course=TeacherNextCourse(**next_course_raw) if next_course_raw else None,
        upcoming_evaluations=[TeacherUpcomingEval(**e) for e in upcoming_raw],
        current_academic_year=current_ay_name,
    )


async def list_evaluations(db: AsyncSession, user_id: int) -> list[TeacherUpcomingEval]:
    """Liste toutes les évaluations du prof, sans cutoff ni limite."""
    teacher = await _get_teacher_for_user(db, user_id)
    rows = await repo.list_upcoming_evaluations(db, teacher.id, limit=None, cutoff_days=None)
    return [TeacherUpcomingEval(**e) for e in rows]


async def get_class_attendance(
    db: AsyncSession,
    user_id: int,
    class_id: int,
    *,
    academic_year_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> ClassAttendanceStats:
    """Stats de presence pour une classe, avec verification d'assignation."""
    teacher = await _get_teacher_for_user(db, user_id)
    # Verify the teacher is assigned to this class
    classes = await repo.get_teacher_classes(db, teacher.id)
    class_ids = {c["class_id"] for c in classes}
    if class_id not in class_ids:
        raise HTTPException(status_code=403, detail="Vous n'etes pas assigne a cette classe")
    return await attendance_service.get_class_stats(
        db,
        class_id,
        academic_year_id=academic_year_id,
        date_from=date_from,
        date_to=date_to,
    )


async def get_class_roster(
    db: AsyncSession, user_id: int, class_id: int
) -> TeacherClassRosterResponse:
    """Liste des élèves inscrits d'une classe assignée à l'enseignant (pour l'appel)."""
    teacher = await _get_teacher_for_user(db, user_id)
    classes = await repo.get_teacher_classes(db, teacher.id)
    match = next((c for c in classes if c["class_id"] == class_id), None)
    if match is None:
        raise HTTPException(status_code=403, detail="Vous n'etes pas assigne a cette classe")

    ay_id = await admin_repository.get_current_academic_year_id(db)
    if ay_id is None:
        raise HTTPException(status_code=400, detail="Aucune annee scolaire active")

    students = await reports_repository.get_enrolled_students(db, class_id, ay_id)
    return TeacherClassRosterResponse(
        class_id=class_id,
        class_name=match["class_name"],
        academic_year_id=ay_id,
        students=[
            TeacherRosterStudent(
                student_id=s.id,
                first_name=s.first_name,
                last_name=s.last_name,
                matricule=s.enrollment_number,
                photo_url=s.photo_url,
            )
            for s in students
        ],
    )
