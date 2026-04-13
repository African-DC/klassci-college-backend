"""Tache Celery — generation asynchrone de l'emploi du temps."""

import asyncio
import logging
from datetime import time
from typing import Any

from app.core.celery_app import celery_app
from app.core.database import _get_session_factory, current_tenant_id

logger = logging.getLogger(__name__)


def _parse_time(t: str) -> time:
    """Convertit "HH:MM" en datetime.time."""
    h, m = t.split(":")
    return time(int(h), int(m))


@celery_app.task(bind=True, name="timetable.generate")  # type: ignore[misc]
def generate_timetable_task(
    self: Any,
    tenant_id: str,
    class_id: int,
    academic_year_id: int,
    assignments_data: list[dict[str, Any]],
    slots_data: list[dict[str, Any]],
    room_id: int | None,
    manual_fixed: list[dict[str, int]] | None = None,
    cross_class_blocked: dict[str, list[int]] | None = None,
    preferred_slots: dict[str, list[int]] | None = None,
) -> dict[str, Any]:
    """Genere un emploi du temps via OR-Tools et persiste les creneaux en DB."""
    try:
        result = asyncio.run(
            _generate_async(
                tenant_id=tenant_id,
                class_id=class_id,
                academic_year_id=academic_year_id,
                assignments_data=assignments_data,
                slots_data=slots_data,
                room_id=room_id,
                manual_fixed=manual_fixed or [],
                cross_class_blocked=cross_class_blocked or {},
                preferred_slots=preferred_slots or {},
            )
        )
        return {"slots": result}
    except Exception as exc:
        logger.exception("Timetable generation failed for tenant=%s class=%s", tenant_id, class_id)
        raise exc


async def _generate_async(
    tenant_id: str,
    class_id: int,
    academic_year_id: int,
    assignments_data: list[dict[str, Any]],
    slots_data: list[dict[str, Any]],
    room_id: int | None,
    manual_fixed: list[dict[str, int]],
    cross_class_blocked: dict[str, list[int]],
    preferred_slots: dict[str, list[int]],
) -> list[dict[str, Any]]:
    """Corps async de la generation — cree les creneaux en DB."""
    from app.repositories import timetable_repository as repo
    from app.utils.timetable_generator import (
        Assignment, FixedAssignment, GeneratorResult, SlotTemplate, solve,
    )

    current_tenant_id.set(tenant_id)
    factory = await _get_session_factory(tenant_id)

    async with factory() as db:
        # Load teacher unavailabilities from DB
        teacher_unavailabilities: dict[int, set[int]] = {}
        unique_teachers = {a["teacher_id"] for a in assignments_data}

        parsed_slots = [
            {
                "day": s["day"],
                "start_time": _parse_time(s["start_time"]),
                "end_time": _parse_time(s["end_time"]),
            }
            for s in slots_data
        ]

        for tid in unique_teachers:
            blocked = await repo.get_unavailable_slot_indices(db, tid, parsed_slots)
            if blocked:
                teacher_unavailabilities[tid] = blocked

        # Merge cross-class conflicts into unavailabilities
        for tid_str, indices in cross_class_blocked.items():
            tid = int(tid_str)
            existing = teacher_unavailabilities.get(tid, set())
            teacher_unavailabilities[tid] = existing | set(indices)

        # Build solver objects
        assignments = [
            Assignment(
                teacher_id=a["teacher_id"],
                subject_id=a["subject_id"],
                hours_per_week=a["hours_per_week"],
            )
            for a in assignments_data
        ]
        slot_templates = [
            SlotTemplate(
                day=s["day"],
                start_time=_parse_time(s["start_time"]),
                end_time=_parse_time(s["end_time"]),
                room_id=room_id,
            )
            for s in slots_data
        ]

        # Build fixed assignments
        fixed = [
            FixedAssignment(assignment_idx=f["assignment_idx"], slot_idx=f["slot_idx"])
            for f in manual_fixed
        ]

        # Build preferred slots (convert str keys back to int)
        pref: dict[int, set[int]] = {
            int(tid_str): set(indices)
            for tid_str, indices in preferred_slots.items()
        }

        # Solve
        gen_result: GeneratorResult = solve(
            assignments, slot_templates, teacher_unavailabilities,
            fixed_assignments=fixed if fixed else None,
            preferred_slots=pref if pref else None,
        )
        if not gen_result.feasible:
            raise ValueError("OR-Tools: aucun emploi du temps faisable avec les contraintes donnees")

        # Create timetable header
        timetable = await repo.create_timetable(
            db, class_id=class_id, academic_year_id=academic_year_id
        )

        # Filter out fixed assignments (manual slots already exist in DB)
        fixed_set = {(f["assignment_idx"], f["slot_idx"]) for f in manual_fixed}
        new_pairs = [
            (a_idx, s_idx) for a_idx, s_idx in gen_result.assignments
            if (a_idx, s_idx) not in fixed_set
        ]

        # Persist only new slots
        slots_to_create = [
            {
                "class_id": class_id,
                "teacher_id": assignments[a_idx].teacher_id,
                "subject_id": assignments[a_idx].subject_id,
                "academic_year_id": academic_year_id,
                "day": slot_templates[s_idx].day,
                "start_time": slot_templates[s_idx].start_time,
                "end_time": slot_templates[s_idx].end_time,
                "room_id": room_id,
            }
            for a_idx, s_idx in new_pairs
        ]
        created_slots = await repo.create_slots_bulk(db, slots_to_create, timetable.id)
        await db.commit()

        # Build response
        slot_responses = []
        for slot in created_slots:
            refreshed = await repo.get_slot_by_id(db, slot.id)
            if refreshed:
                slot_responses.append(_slot_to_dict(refreshed))

        # Also include manual slots in the response
        manual_slots = await repo.list_manual_slots_for_class(db, class_id)
        for ms in manual_slots:
            slot_responses.append(_slot_to_dict(ms))

        return slot_responses


def _slot_to_dict(slot: Any) -> dict[str, Any]:
    """Convertit un TimetableSlot ORM en dict JSON-serialisable."""
    teacher_name = f"{slot.teacher.first_name} {slot.teacher.last_name}" if slot.teacher else ""
    return {
        "id": slot.id,
        "class_id": slot.class_id,
        "class_name": slot.class_.name if slot.class_ else "",
        "teacher_id": slot.teacher_id,
        "teacher_name": teacher_name,
        "subject_id": slot.subject_id,
        "subject_name": slot.subject.name if slot.subject else "",
        "subject_color": getattr(slot.subject, "color", None) if slot.subject else None,
        "academic_year_id": slot.academic_year_id,
        "day": slot.day if isinstance(slot.day, str) else slot.day.value,
        "start_time": slot.start_time.strftime("%H:%M"),
        "end_time": slot.end_time.strftime("%H:%M"),
        "room": slot.room.name if slot.room else None,
    }
