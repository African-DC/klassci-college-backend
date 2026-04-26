"""Tache Celery — generation asynchrone de l'emploi du temps."""

import asyncio
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.celery_app import celery_app
from app.core.config import settings
from app.core.database import current_tenant_id

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name="timetable.generate")  # type: ignore[misc]
def generate_timetable_task(
    self: Any,
    tenant_id: str,
    class_id: int,
    academic_year_id: int,
    assignments_data: list[dict[str, Any]],
    day_names: list[str],
    day_start_hour: int,
    day_end_hour: int,
    slot_duration_minutes: int,
    room_id: int | None,
    manual_fixed: list[dict[str, int]] | None = None,
    cross_class_blocked: dict[str, list[int]] | None = None,
    preferred_blocks: dict[str, list[int]] | None = None,
) -> dict[str, Any]:
    """Genere un emploi du temps via OR-Tools et persiste les creneaux en DB."""
    try:
        result = asyncio.run(
            _generate_async(
                tenant_id=tenant_id,
                class_id=class_id,
                academic_year_id=academic_year_id,
                assignments_data=assignments_data,
                day_names=day_names,
                day_start_hour=day_start_hour,
                day_end_hour=day_end_hour,
                slot_duration_minutes=slot_duration_minutes,
                room_id=room_id,
                manual_fixed=manual_fixed or [],
                cross_class_blocked=cross_class_blocked or {},
                preferred_blocks=preferred_blocks or {},
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
    day_names: list[str],
    day_start_hour: int,
    day_end_hour: int,
    slot_duration_minutes: int,
    room_id: int | None,
    manual_fixed: list[dict[str, int]],
    cross_class_blocked: dict[str, list[int]],
    preferred_blocks: dict[str, list[int]],
) -> list[dict[str, Any]]:
    """Corps async de la generation — solveur + persistence."""
    from app.repositories import timetable_repository as repo
    from app.utils.timetable_generator import (
        Assignment,
        FixedBlock,
        build_blocks,
        solve,
    )

    current_tenant_id.set(tenant_id)
    db_url = settings.DATABASE_URL.format(tenant=tenant_id)
    engine = create_async_engine(db_url, echo=False)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with factory() as db:
        # Build the block grid
        grid_blocks = build_blocks(day_names, day_start_hour, day_end_hour, slot_duration_minutes)

        # Build assignments
        assignments = [
            Assignment(
                teacher_id=a["teacher_id"],
                subject_id=a["subject_id"],
                hours_per_week=a["hours_per_week"],
            )
            for a in assignments_data
        ]

        # Load teacher unavailabilities from DB
        teacher_unavailabilities: dict[int, set[int]] = {}
        unique_teachers = {a["teacher_id"] for a in assignments_data}

        for tid in unique_teachers:
            blocked = await repo.get_unavailable_block_indices(db, tid, grid_blocks)
            if blocked:
                teacher_unavailabilities[tid] = blocked

        # Merge cross-class conflicts
        for tid_str, indices in cross_class_blocked.items():
            tid = int(tid_str)
            existing = teacher_unavailabilities.get(tid, set())
            teacher_unavailabilities[tid] = existing | set(indices)

        # Build fixed blocks
        fixed = [
            FixedBlock(assignment_idx=f["assignment_idx"], block_idx=f["block_idx"])
            for f in manual_fixed
        ]

        # Build preferred blocks
        pref: dict[int, set[int]] = {
            int(tid_str): set(indices) for tid_str, indices in preferred_blocks.items()
        }

        # Solve
        gen_result = solve(
            assignments=assignments,
            blocks=grid_blocks,
            slot_duration_minutes=slot_duration_minutes,
            teacher_unavailabilities=teacher_unavailabilities,
            fixed_blocks=fixed if fixed else None,
            preferred_blocks=pref if pref else None,
        )
        if not gen_result.feasible:
            raise ValueError(
                "OR-Tools: aucun emploi du temps faisable avec les contraintes donnees"
            )

        # Create timetable header
        timetable = await repo.create_timetable(
            db, class_id=class_id, academic_year_id=academic_year_id
        )

        # Filter out merged slots that correspond to manual fixed blocks
        # (manual slots already exist in DB, don't duplicate)
        manual_block_set = {(f["assignment_idx"], f["block_idx"]) for f in manual_fixed}

        # Determine which merged slots are new vs manual
        # A merged slot is "manual" if ALL its constituent blocks are in the fixed set
        new_merged = []
        for ms in gen_result.merged_slots:
            # Check if this merged slot overlaps with manual blocks
            ms_start_min = ms.start_time.hour * 60 + ms.start_time.minute
            ms_end_min = ms.end_time.hour * 60 + ms.end_time.minute
            is_manual = False
            for blk in grid_blocks:
                if (
                    blk.day == ms.day
                    and blk.start_minutes >= ms_start_min
                    and blk.end_minutes <= ms_end_min
                ):
                    if (ms.assignment_idx, blk.index) in manual_block_set:
                        is_manual = True
                        break
            if not is_manual:
                new_merged.append(ms)

        # Persist new merged slots
        slots_to_create = [
            {
                "class_id": class_id,
                "teacher_id": assignments[ms.assignment_idx].teacher_id,
                "subject_id": assignments[ms.assignment_idx].subject_id,
                "academic_year_id": academic_year_id,
                "day": ms.day,
                "start_time": ms.start_time,
                "end_time": ms.end_time,
                "room_id": room_id,
            }
            for ms in new_merged
        ]
        created_slots = await repo.create_slots_bulk(db, slots_to_create, timetable.id)
        await db.commit()

        # Build response (include both new and manual slots)
        slot_responses = []
        for slot in created_slots:
            refreshed = await repo.get_slot_by_id(db, slot.id)
            if refreshed:
                slot_responses.append(_slot_to_dict(refreshed))

        manual_slots = await repo.list_manual_slots_for_class(db, class_id)
        for ms in manual_slots:
            slot_responses.append(_slot_to_dict(ms))

        await engine.dispose()
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
        "day": slot.day if isinstance(slot.day, str) else slot.day,
        "start_time": slot.start_time.strftime("%H:%M"),
        "end_time": slot.end_time.strftime("%H:%M"),
        "room": slot.room.name if slot.room else None,
    }
