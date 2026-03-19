"""Tâche Celery — génération asynchrone de l'emploi du temps."""

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


@celery_app.task(bind=True, name="timetable.generate")  # type: ignore[untyped-decorator]
def generate_timetable_task(
    self: Any,
    tenant_id: str,
    class_id: int,
    academic_year_id: int,
    assignments_data: list[dict[str, Any]],
    slots_data: list[dict[str, Any]],
    room_id: int | None,
) -> dict[str, Any]:
    """Génère un emploi du temps via OR-Tools et persiste les créneaux en DB.

    Retourne un dict compatible avec TaskStatusResponse.result (list of slot dicts).
    """
    try:
        result = asyncio.run(
            _generate_async(
                tenant_id=tenant_id,
                class_id=class_id,
                academic_year_id=academic_year_id,
                assignments_data=assignments_data,
                slots_data=slots_data,
                room_id=room_id,
            )
        )
        return {"slots": result}
    except Exception as exc:
        logger.exception("Timetable generation failed for tenant=%s class=%s", tenant_id, class_id)
        raise self.retry(exc=exc, countdown=5, max_retries=0) from exc


async def _generate_async(
    tenant_id: str,
    class_id: int,
    academic_year_id: int,
    assignments_data: list[dict[str, Any]],
    slots_data: list[dict[str, Any]],
    room_id: int | None,
) -> list[dict[str, Any]]:
    """Corps async de la génération — crée les créneaux en DB."""
    from app.repositories import timetable_repository as repo
    from app.utils.timetable_generator import Assignment, GeneratorResult, SlotTemplate, solve

    # Configurer le tenant_id dans le contexte
    current_tenant_id.set(tenant_id)
    factory = await _get_session_factory(tenant_id)

    async with factory() as db:
        # Charger les indisponibilités pour chaque enseignant
        teacher_unavailabilities: dict[int, set[int]] = {}
        unique_teachers = {a["teacher_id"] for a in assignments_data}

        # Préparer les créneaux disponibles sous forme de dicts avec time objects
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

        # Construire les objets pour le solveur
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
            )
            for s in slots_data
        ]

        # Lancer le solveur
        gen_result: GeneratorResult = solve(assignments, slot_templates, teacher_unavailabilities)
        if not gen_result.feasible:
            raise ValueError("OR-Tools: no feasible timetable found with given constraints")

        # Créer le header Timetable
        timetable = await repo.create_timetable(
            db, class_id=class_id, academic_year_id=academic_year_id
        )

        # Persister les créneaux
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
            for a_idx, s_idx in gen_result.assignments
        ]
        created_slots = await repo.create_slots_bulk(db, slots_to_create, timetable.id)
        await db.commit()

        # Recharger avec les relations pour construire la réponse
        slot_responses = []
        for slot in created_slots:
            refreshed = await repo.get_slot_by_id(db, slot.id)
            if refreshed:
                slot_responses.append(_slot_to_dict(refreshed))

        return slot_responses


def _slot_to_dict(slot: Any) -> dict[str, Any]:
    """Convertit un TimetableSlot ORM en dict JSON-sérialisable."""
    teacher_name = f"{slot.teacher.first_name} {slot.teacher.last_name}" if slot.teacher else ""
    return {
        "id": slot.id,
        "class_id": slot.class_id,
        "class_name": slot.class_.name if slot.class_ else "",
        "teacher_id": slot.teacher_id,
        "teacher_name": teacher_name,
        "subject_id": slot.subject_id,
        "subject_name": slot.subject.name if slot.subject else "",
        "academic_year_id": slot.academic_year_id,
        "day": slot.day if isinstance(slot.day, str) else slot.day.value,
        "start_time": slot.start_time.strftime("%H:%M"),
        "end_time": slot.end_time.strftime("%H:%M"),
        "room": slot.room.name if slot.room else None,
    }
