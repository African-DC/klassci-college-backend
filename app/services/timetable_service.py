"""Service emploi du temps — logique métier CRUD + génération OR-Tools."""

import logging
from datetime import time

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.audit import AuditAction, audit_log
from app.core.exceptions import BusinessValidationError, ConflictError, NotFoundError
from app.models.timetable import TeacherAvailability, TimetableSlot
from app.repositories import timetable_repository as repo
from app.schemas.timetable import (
    GenerateTimetableRequest,
    GenerateTimetableResponse,
    TaskStatusResponse,
    TeacherAvailabilityCreate,
    TeacherAvailabilityResponse,
    TeacherAvailabilityUpdate,
    TimetableSlotCreate,
    TimetableSlotResponse,
    TimetableSlotUpdate,
)

logger = logging.getLogger(__name__)


def _parse_time(t: str) -> time:
    """Convertit "HH:MM" en datetime.time."""
    h, m = t.split(":")
    return time(int(h), int(m))


def _to_slot_response(slot: TimetableSlot) -> TimetableSlotResponse:
    """Convertit un TimetableSlot ORM en TimetableSlotResponse."""
    teacher_name = f"{slot.teacher.first_name} {slot.teacher.last_name}" if slot.teacher else ""
    return TimetableSlotResponse(
        id=slot.id,
        class_id=slot.class_id,
        class_name=slot.class_.name if slot.class_ else "",
        teacher_id=slot.teacher_id,
        teacher_name=teacher_name,
        subject_id=slot.subject_id,
        subject_name=slot.subject.name if slot.subject else "",
        subject_color=slot.subject.color if slot.subject else None,
        academic_year_id=slot.academic_year_id,
        day=slot.day,
        start_time=slot.start_time.strftime("%H:%M"),
        end_time=slot.end_time.strftime("%H:%M"),
        room=slot.room.name if slot.room else None,
    )


def _to_availability_response(av: TeacherAvailability) -> TeacherAvailabilityResponse:
    """Convertit une TeacherAvailability ORM en TeacherAvailabilityResponse."""
    return TeacherAvailabilityResponse(
        id=av.id,
        teacher_id=av.teacher_id,
        day=av.day,
        start_time=av.start_time.strftime("%H:%M"),
        end_time=av.end_time.strftime("%H:%M"),
        available=av.available,
        preferred=av.preferred,
    )


# ---------------------------------------------------------------------------
# Slot CRUD
# ---------------------------------------------------------------------------


async def list_slots(
    db: AsyncSession,
    *,
    class_id: int | None = None,
    teacher_id: int | None = None,
    academic_year_id: int | None = None,
) -> list[TimetableSlotResponse]:
    """Liste les créneaux avec filtres optionnels."""
    slots = await repo.list_slots(
        db,
        class_id=class_id,
        teacher_id=teacher_id,
        academic_year_id=academic_year_id,
    )
    return [_to_slot_response(s) for s in slots]


async def get_slot(db: AsyncSession, slot_id: int) -> TimetableSlotResponse:
    """Retourne un créneau par ID ou lève 404."""
    slot = await repo.get_slot_by_id(db, slot_id)
    if slot is None:
        raise NotFoundError("TimetableSlot", slot_id)
    return _to_slot_response(slot)


async def create_slot(
    db: AsyncSession,
    data: TimetableSlotCreate,
    created_by: int,
) -> TimetableSlotResponse:
    """Crée un créneau — vérifie les conflits d'abord."""
    start = _parse_time(data.start_time)
    end = _parse_time(data.end_time)

    if start >= end:
        raise BusinessValidationError("start_time must be before end_time")

    # Résoudre la salle par nom si fourni
    room_id: int | None = None
    if data.room is not None:
        room = await repo.get_room_by_name(db, data.room)
        if room is None:
            raise BusinessValidationError(f"Room '{data.room}' not found")
        room_id = room.id

    # Vérifier les conflits
    if await repo.check_teacher_conflict(db, data.teacher_id, data.day.value, start, end):
        raise ConflictError(
            f"Teacher {data.teacher_id} already has a class on {data.day.value} "
            f"at {data.start_time}–{data.end_time}"
        )
    if await repo.check_class_conflict(db, data.class_id, data.day.value, start, end):
        raise ConflictError(
            f"Class {data.class_id} already has a class on {data.day.value} "
            f"at {data.start_time}–{data.end_time}"
        )

    slot = await repo.create_slot(
        db,
        class_id=data.class_id,
        teacher_id=data.teacher_id,
        subject_id=data.subject_id,
        academic_year_id=data.academic_year_id,
        day=data.day.value,
        start_time=start,
        end_time=end,
        room_id=room_id,
    )
    await db.commit()

    refreshed = await repo.get_slot_by_id(db, slot.id)
    assert refreshed is not None

    await audit_log(
        db,
        entity_type="timetable_slot",
        action=AuditAction.CREATE,
        user_id=created_by,
        entity_id=slot.id,
        new_values=data.model_dump(),
    )
    await db.commit()

    return _to_slot_response(refreshed)


async def update_slot(
    db: AsyncSession,
    slot_id: int,
    data: TimetableSlotUpdate,
    updated_by: int,
) -> TimetableSlotResponse:
    """Met à jour un créneau (patch partiel) — vérifie les conflits."""
    slot = await repo.get_slot_by_id(db, slot_id)
    if slot is None:
        raise NotFoundError("TimetableSlot", slot_id)

    # Fusionner avec les valeurs existantes
    new_day = data.day.value if data.day is not None else slot.day
    new_start = _parse_time(data.start_time) if data.start_time else slot.start_time
    new_end = _parse_time(data.end_time) if data.end_time else slot.end_time
    new_teacher_id = data.teacher_id if data.teacher_id is not None else slot.teacher_id

    if new_start >= new_end:
        raise BusinessValidationError("start_time must be before end_time")

    # Résoudre la salle
    new_room_id: int | None
    if data.room is not None:
        if data.room == "":
            new_room_id = None
        else:
            room = await repo.get_room_by_name(db, data.room)
            if room is None:
                raise BusinessValidationError(f"Room '{data.room}' not found")
            new_room_id = room.id
    else:
        new_room_id = slot.room_id

    # Vérifier les conflits (en excluant le slot courant)
    if await repo.check_teacher_conflict(
        db, new_teacher_id, new_day, new_start, new_end, exclude_slot_id=slot_id
    ):
        raise ConflictError(f"Teacher {new_teacher_id} already has a class on {new_day}")
    if await repo.check_class_conflict(
        db, slot.class_id, new_day, new_start, new_end, exclude_slot_id=slot_id
    ):
        raise ConflictError(f"Class {slot.class_id} already has a class on {new_day}")

    old_values = {
        "day": slot.day,
        "start_time": slot.start_time.strftime("%H:%M"),
        "end_time": slot.end_time.strftime("%H:%M"),
        "teacher_id": slot.teacher_id,
        "subject_id": slot.subject_id,
    }

    await repo.update_slot(
        db,
        slot,
        teacher_id=data.teacher_id,
        subject_id=data.subject_id,
        day=new_day if data.day is not None else None,
        start_time=new_start if data.start_time else None,
        end_time=new_end if data.end_time else None,
        room_id=new_room_id,
    )
    await db.commit()

    await audit_log(
        db,
        entity_type="timetable_slot",
        action=AuditAction.UPDATE,
        user_id=updated_by,
        entity_id=slot_id,
        old_values=old_values,
        new_values=data.model_dump(exclude_none=True),
    )
    await db.commit()

    refreshed = await repo.get_slot_by_id(db, slot_id)
    assert refreshed is not None
    return _to_slot_response(refreshed)


async def delete_slot(
    db: AsyncSession,
    slot_id: int,
    deleted_by: int,
) -> None:
    """Supprime un créneau ou lève 404."""
    slot = await repo.get_slot_by_id(db, slot_id)
    if slot is None:
        raise NotFoundError("TimetableSlot", slot_id)

    await repo.delete_slot(db, slot)
    await db.commit()

    await audit_log(
        db,
        entity_type="timetable_slot",
        action=AuditAction.DELETE,
        user_id=deleted_by,
        entity_id=slot_id,
    )
    await db.commit()


# ---------------------------------------------------------------------------
# OR-Tools generation
# ---------------------------------------------------------------------------


async def diagnostic_for_class(
    db: AsyncSession,
    class_id: int,
) -> dict:
    """Diagnostic pre-generation : verifie les prerequis avant de generer.

    Retourne un dict avec :
    - ready: bool
    - subjects_without_teacher: list of {id, name, hours_per_week}
    - subjects_with_teacher: list of {id, name, hours_per_week, teacher_name}
    - total_hours_required: int
    - total_slots_available: int
    - manual_slots_count: int
    """
    from sqlalchemy import select, or_, func
    from app.models.academic import Class, Subject

    cls = (await db.execute(
        select(Class).where(Class.id == class_id)
    )).scalar_one_or_none()
    if cls is None:
        raise NotFoundError("Class", class_id)

    # Get subjects for this level
    subjects_stmt = (
        select(Subject)
        .where(Subject.level_id == cls.level_id)
        .options(selectinload(Subject.teacher))
    )
    if cls.series_id:
        subjects_stmt = subjects_stmt.where(
            or_(Subject.series_id == cls.series_id, Subject.series_id.is_(None))
        )
    subjects = list((await db.execute(subjects_stmt)).scalars().all())

    without_teacher = []
    with_teacher = []
    total_hours = 0

    for s in subjects:
        total_hours += s.hours_per_week
        if s.teacher_id and s.teacher:
            with_teacher.append({
                "id": s.id,
                "name": s.name,
                "hours_per_week": s.hours_per_week,
                "teacher_id": s.teacher_id,
                "teacher_name": f"{s.teacher.first_name} {s.teacher.last_name}",
            })
        else:
            without_teacher.append({
                "id": s.id,
                "name": s.name,
                "hours_per_week": s.hours_per_week,
            })

    # Count manual slots for this class
    manual_count_stmt = (
        select(func.count())
        .select_from(TimetableSlot)
        .where(TimetableSlot.class_id == class_id, TimetableSlot.timetable_id.is_(None))
    )
    manual_count = (await db.execute(manual_count_stmt)).scalar() or 0

    # 6 days * 10 hours = 60 slots available
    total_slots = 6 * 10

    return {
        "ready": len(without_teacher) == 0 and len(subjects) > 0,
        "class_id": class_id,
        "class_name": cls.name,
        "subjects_without_teacher": without_teacher,
        "subjects_with_teacher": with_teacher,
        "total_hours_required": total_hours,
        "total_slots_available": total_slots,
        "manual_slots_count": manual_count,
    }


async def auto_generate(
    db: AsyncSession,
    tenant_id: str,
    class_id: int,
) -> GenerateTimetableResponse:
    """Generation automatique intelligente.

    1. Recupere la classe et ses matieres
    2. Verifie que TOUTES les matieres ont un enseignant
    3. Charge les slots manuels existants (timetable_id IS NULL) comme contraintes fixes
    4. Charge les conflits inter-classes (profs + salles deja occupes)
    5. Charge les creneaux preferes des enseignants
    6. Supprime seulement les slots auto-generes (timetable_id IS NOT NULL)
    7. Lance le solveur OR-Tools avec toutes les contraintes
    """
    from sqlalchemy import select, or_, delete
    from app.models.academic import Class, Subject

    # 1. Get class
    cls = (await db.execute(
        select(Class).where(Class.id == class_id)
    )).scalar_one_or_none()
    if cls is None:
        raise NotFoundError("Class", class_id)

    # 2. Get subjects for this level
    subjects_stmt = select(Subject).where(Subject.level_id == cls.level_id)
    if cls.series_id:
        subjects_stmt = subjects_stmt.where(
            or_(Subject.series_id == cls.series_id, Subject.series_id.is_(None))
        )
    subjects = list((await db.execute(subjects_stmt)).scalars().all())

    if not subjects:
        raise BusinessValidationError(
            "Aucune matiere assignee a ce niveau. Assignez des matieres dans le Kanban d'abord."
        )

    # Check ALL subjects have teachers
    without_teacher = [s for s in subjects if not s.teacher_id]
    if without_teacher:
        names = ", ".join(s.name for s in without_teacher)
        raise BusinessValidationError(
            f"Matieres sans enseignant : {names}. Utilisez le diagnostic pour les assigner."
        )

    # 3. Build assignments
    from app.schemas.timetable import AssignmentInput, TimeSlotInput
    assignments_input = [
        AssignmentInput(
            teacher_id=s.teacher_id,
            subject_id=s.id,
            hours_per_week=s.hours_per_week,
        )
        for s in subjects
    ]

    # 4. Default available slots: Mon-Sat, 07:00-17:00, 1h each
    from app.models.timetable import DayOfWeek
    days = [DayOfWeek.MONDAY, DayOfWeek.TUESDAY, DayOfWeek.WEDNESDAY,
            DayOfWeek.THURSDAY, DayOfWeek.FRIDAY, DayOfWeek.SATURDAY]
    available_slots = []
    for day in days:
        for hour in range(7, 17):
            available_slots.append(TimeSlotInput(
                day=day,
                start_time=f"{hour:02d}:00",
                end_time=f"{hour + 1:02d}:00",
            ))

    # 5. Delete only auto-generated slots (keep manual ones)
    del_stmt = delete(TimetableSlot).where(
        TimetableSlot.class_id == class_id,
        TimetableSlot.timetable_id.is_not(None),
    )
    await db.execute(del_stmt)
    await db.flush()

    # 6. Load manual slots as fixed assignments for the solver
    # These will be passed to the Celery task
    manual_slots = await repo.list_manual_slots_for_class(db, class_id)
    manual_fixed_data = []
    for ms in manual_slots:
        # Find which assignment index this manual slot maps to
        for idx, ai in enumerate(assignments_input):
            if ai.subject_id == ms.subject_id and ai.teacher_id == ms.teacher_id:
                # Find which slot index this maps to
                day_val = ms.day if isinstance(ms.day, str) else ms.day
                start_str = ms.start_time.strftime("%H:%M")
                for sidx, sl in enumerate(available_slots):
                    if sl.day.value == day_val and sl.start_time == start_str:
                        manual_fixed_data.append({"assignment_idx": idx, "slot_idx": sidx})
                        break
                break

    # 7. Load cross-class conflicts for each teacher
    teacher_ids = {s.teacher_id for s in subjects}
    cross_class_blocked: dict[int, set[int]] = {}
    for tid in teacher_ids:
        blocked = await repo.get_cross_class_blocked_slots(
            db, tid, class_id, available_slots,
        )
        if blocked:
            cross_class_blocked[tid] = blocked

    # 8. Load preferred slots for each teacher
    preferred_data: dict[int, list[int]] = {}
    for tid in teacher_ids:
        pref_indices = await repo.get_preferred_slot_indices(db, tid, available_slots)
        if pref_indices:
            preferred_data[tid] = list(pref_indices)

    await db.commit()

    # 9. Build request and trigger
    request = GenerateTimetableRequest(
        class_id=class_id,
        academic_year_id=cls.academic_year_id,
        assignments=assignments_input,
        available_slots=available_slots,
        room_id=cls.room_id,
    )
    return trigger_generate(
        tenant_id, request,
        manual_fixed=manual_fixed_data,
        cross_class_blocked=cross_class_blocked,
        preferred_slots=preferred_data,
    )


def trigger_generate(
    tenant_id: str,
    request: GenerateTimetableRequest,
    manual_fixed: list[dict] | None = None,
    cross_class_blocked: dict[int, set[int]] | None = None,
    preferred_slots: dict[int, list[int]] | None = None,
) -> GenerateTimetableResponse:
    """Dispatche la generation OR-Tools comme tache Celery."""
    from app.tasks.timetable_tasks import generate_timetable_task

    # Serialize sets to lists for JSON
    serialized_blocked = {
        str(k): list(v) for k, v in (cross_class_blocked or {}).items()
    }
    serialized_preferred = {
        str(k): v for k, v in (preferred_slots or {}).items()
    }

    task = generate_timetable_task.delay(
        tenant_id,
        request.class_id,
        request.academic_year_id,
        [a.model_dump() for a in request.assignments],
        [s.model_dump() for s in request.available_slots],
        request.room_id,
        manual_fixed or [],
        serialized_blocked,
        serialized_preferred,
    )
    return GenerateTimetableResponse(task_id=str(task.id))


def get_task_status(task_id: str) -> TaskStatusResponse:
    """Retourne le statut d'une tâche Celery."""
    from celery.result import AsyncResult

    from app.core.celery_app import celery_app

    result = AsyncResult(task_id, app=celery_app)

    state_map = {
        "PENDING": "pending",
        "STARTED": "running",
        "RETRY": "running",
        "SUCCESS": "completed",
        "FAILURE": "failed",
    }
    status = state_map.get(result.state, "pending")

    task_result: list[TimetableSlotResponse] | None = None
    if result.state == "SUCCESS" and isinstance(result.result, dict):
        raw_slots = result.result.get("slots", [])
        task_result = [TimetableSlotResponse(**s) for s in raw_slots]

    return TaskStatusResponse(status=status, result=task_result)


# ---------------------------------------------------------------------------
# Teacher availability
# ---------------------------------------------------------------------------


async def list_teacher_availabilities(
    db: AsyncSession, teacher_id: int
) -> list[TeacherAvailabilityResponse]:
    """Retourne les disponibilités d'un enseignant."""
    avs = await repo.list_teacher_availabilities(db, teacher_id)
    return [_to_availability_response(av) for av in avs]


async def create_teacher_availability(
    db: AsyncSession,
    teacher_id: int,
    data: TeacherAvailabilityCreate,
) -> TeacherAvailabilityResponse:
    """Crée une entrée de disponibilité enseignant."""
    start = _parse_time(data.start_time)
    end = _parse_time(data.end_time)
    if start >= end:
        raise BusinessValidationError("start_time must be before end_time")

    av = await repo.create_teacher_availability(
        db,
        teacher_id=teacher_id,
        day=data.day.value,
        start_time=start,
        end_time=end,
        available=data.available,
        preferred=data.preferred,
    )
    await db.commit()
    return _to_availability_response(av)


async def update_teacher_availability(
    db: AsyncSession,
    av_id: int,
    data: TeacherAvailabilityUpdate,
) -> TeacherAvailabilityResponse:
    """Met à jour une disponibilité enseignant (available/preferred)."""
    av = await repo.get_teacher_availability_by_id(db, av_id)
    if av is None:
        raise NotFoundError("TeacherAvailability", av_id)
    av = await repo.update_teacher_availability(
        db, av, available=data.available, preferred=data.preferred,
    )
    await db.commit()
    return _to_availability_response(av)


async def delete_teacher_availability(
    db: AsyncSession,
    av_id: int,
) -> None:
    """Supprime une disponibilité enseignant ou lève 404."""
    av = await repo.get_teacher_availability_by_id(db, av_id)
    if av is None:
        raise NotFoundError("TeacherAvailability", av_id)
    await repo.delete_teacher_availability(db, av)
    await db.commit()
