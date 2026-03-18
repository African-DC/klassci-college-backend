"""Service emploi du temps — logique métier CRUD + génération OR-Tools."""

import logging
from datetime import time

from sqlalchemy.ext.asyncio import AsyncSession

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
        academic_year_id=slot.academic_year_id,
        day=slot.day if isinstance(slot.day, str) else slot.day.value,
        start_time=slot.start_time.strftime("%H:%M"),
        end_time=slot.end_time.strftime("%H:%M"),
        room=slot.room.name if slot.room else None,
    )


def _to_availability_response(av: TeacherAvailability) -> TeacherAvailabilityResponse:
    """Convertit une TeacherAvailability ORM en TeacherAvailabilityResponse."""
    return TeacherAvailabilityResponse(
        id=av.id,
        teacher_id=av.teacher_id,
        day=av.day if isinstance(av.day, str) else av.day.value,
        start_time=av.start_time.strftime("%H:%M"),
        end_time=av.end_time.strftime("%H:%M"),
        available=av.available,
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
    new_day = (
        data.day.value
        if data.day is not None
        else (slot.day if isinstance(slot.day, str) else slot.day.value)
    )
    new_start = _parse_time(data.start_time) if data.start_time else slot.start_time
    new_end = _parse_time(data.end_time) if data.end_time else slot.end_time
    new_teacher_id = data.teacher_id if data.teacher_id is not None else slot.teacher_id

    if new_start >= new_end:
        raise BusinessValidationError("start_time must be before end_time")

    # Résoudre la salle
    if data.room is not None:
        if data.room == "":
            new_room_id = None
        else:
            room = await repo.get_room_by_name(db, data.room)
            if room is None:
                raise BusinessValidationError(f"Room '{data.room}' not found")
            new_room_id: int | None = room.id
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
        "day": slot.day if isinstance(slot.day, str) else slot.day.value,
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


def trigger_generate(
    tenant_id: str,
    request: GenerateTimetableRequest,
) -> GenerateTimetableResponse:
    """Dispatche la génération OR-Tools comme tâche Celery."""
    from app.tasks.timetable_tasks import generate_timetable_task

    task = generate_timetable_task.delay(
        tenant_id,
        request.class_id,
        request.academic_year_id,
        [a.model_dump() for a in request.assignments],
        [s.model_dump() for s in request.available_slots],
        request.room_id,
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
        "SUCCESS": "success",
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
