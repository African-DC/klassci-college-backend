"""Service portail enseignant — logique métier read-only."""

import logging
from datetime import date

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.academic import Class
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
from app.services import attendance_service, schedule_event_service
from app.services.teaching_scope import teaching_scope

logger = logging.getLogger(__name__)


async def _get_teacher_for_user(db: AsyncSession, user_id: int) -> TeacherProfile:
    """Retourne le profil enseignant ou lève NotFoundError."""
    teacher = await repo.get_teacher_by_user_id(db, user_id)
    if teacher is None:
        raise NotFoundError("TeacherProfile", user_id)
    return teacher


async def _require_class_in_scope(db: AsyncSession, user_id: int, class_id: int) -> Class:
    """La classe, si l'enseignant la couvre aujourd'hui (affectation, créneau ou intérim)."""
    teacher = await _get_teacher_for_user(db, user_id)
    scope = await teaching_scope(db, teacher.id)
    klass = await db.get(Class, class_id) if scope.covers_class(class_id) else None
    if klass is None:
        raise HTTPException(status_code=403, detail="Vous n'êtes pas assigné à cette classe")
    return klass


async def resolve_teacher_id(db: AsyncSession, user_id: int) -> int:
    """L'enseignant derriere un compte connecte.

    Expose pour les endpoints qui delegent ensuite a un autre service : ils ont
    besoin de l'identifiant enseignant, pas du profil entier, et surtout pas de
    le rechercher eux-memes avec une autre regle que celle du portail.
    """
    return (await _get_teacher_for_user(db, user_id)).id


async def get_classes(db: AsyncSession, user_id: int) -> TeacherClassesListResponse:
    """Les classes que l'enseignant couvre aujourd'hui, une ligne par matière."""
    teacher = await _get_teacher_for_user(db, user_id)
    scope = await teaching_scope(db, teacher.id)
    classes = await repo.get_teacher_classes(db, scope.class_subjects)
    items = [TeacherClassResponse(**c) for c in classes]
    return TeacherClassesListResponse(items=items, total=len(items))


async def get_schedule(db: AsyncSession, user_id: int) -> TeacherScheduleResponse:
    """Retourne l'emploi du temps personnel de l'enseignant."""
    teacher = await _get_teacher_for_user(db, user_id)
    year_id = await admin_repository.get_current_academic_year_id(db)
    slots = await repo.get_teacher_schedule(db, teacher.id, year_id)
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
    events_by_id = {}
    if year_id is not None:
        for class_id in {slot.class_id for slot in slots}:
            for event in await schedule_event_service.list_events(
                db, academic_year_id=year_id, class_id=class_id
            ):
                events_by_id[event.id] = event
    return TeacherScheduleResponse(
        items=items, total=len(items), events=list(events_by_id.values())
    )


async def get_dashboard_stats(db: AsyncSession, user_id: int) -> TeacherDashboardStats:
    """Retourne le dashboard de l'enseignant connecté.

    Aligné sur le contrat FE `TeacherDashboardSchema` (lib/contracts/teacher-portal.ts) :
    nom, totaux, prochain cours, évaluations à venir/récentes.
    """
    teacher = await _get_teacher_for_user(db, user_id)
    scope = await teaching_scope(db, teacher.id)

    total_classes = len(scope.class_ids)
    total_students = await repo.count_total_students(db, scope.class_ids)
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
    await _require_class_in_scope(db, user_id, class_id)
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
    klass = await _require_class_in_scope(db, user_id, class_id)

    ay_id = await admin_repository.get_current_academic_year_id(db)
    if ay_id is None:
        raise HTTPException(status_code=400, detail="Aucune annee scolaire active")

    students = await reports_repository.get_enrolled_students(db, class_id, ay_id)
    return TeacherClassRosterResponse(
        class_id=class_id,
        class_name=klass.name,
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
