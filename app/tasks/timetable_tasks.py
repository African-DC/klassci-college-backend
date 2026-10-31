"""Tache Celery — generation asynchrone de l'emploi du temps."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
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


@asynccontextmanager
async def _tenant_timetable_session(tenant_id: str) -> AsyncIterator[AsyncSession]:
    """Always close tenant connections and restore context, even on failure."""
    token = current_tenant_id.set(tenant_id)
    engine = None
    try:
        url = settings.DATABASE_URL.format(tenant=tenant_id)
        engine = create_async_engine(url, echo=False)
        factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with factory() as session:
            yield session
    finally:
        if engine is not None:
            await engine.dispose()
        current_tenant_id.reset(token)


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
        build_blocks,
        solve,
    )

    async with _tenant_timetable_session(tenant_id) as db:
        # Locks serialize simultaneous generation jobs sharing a class or
        # teacher. Keep a single transaction through the final replacement.
        from sqlalchemy import select

        from app.models.academic import Class
        from app.models.user import TeacherProfile

        await db.execute(select(Class.id).where(Class.id == class_id).with_for_update())
        for teacher_id in sorted({a["teacher_id"] for a in assignments_data}):
            await db.execute(
                select(TeacherProfile.id).where(TeacherProfile.id == teacher_id).with_for_update()
            )

        # Re-read breaks and manual courses at execution time. Queued jobs
        # must never use an obsolete snapshot of the school's timetable.
        from sqlalchemy import delete, or_, select

        from app.models.timetable import ScheduleEvent, TimetableSlot
        from app.services.schedule_event_service import to_blocked_periods

        events = list(
            (
                await db.execute(
                    select(ScheduleEvent).where(
                        ScheduleEvent.academic_year_id == academic_year_id,
                        or_(
                            ScheduleEvent.class_id.is_(None),
                            ScheduleEvent.class_id == class_id,
                        ),
                    )
                )
            )
            .scalars()
            .all()
        )
        manual = list(
            (
                await db.execute(
                    select(TimetableSlot).where(
                        TimetableSlot.class_id == class_id,
                        TimetableSlot.academic_year_id == academic_year_id,
                        TimetableSlot.timetable_id.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        blocked = to_blocked_periods(events, class_id)
        covered_minutes: dict[tuple[int, int], int] = {}
        for slot in manual:
            day = slot.day.value if hasattr(slot.day, "value") else slot.day
            begin = slot.start_time.hour * 60 + slot.start_time.minute
            end = slot.end_time.hour * 60 + slot.end_time.minute
            if end <= begin:
                raise ValueError("Invalid existing manual lesson interval")
            if any(a < end and b > begin for a, b in blocked.get(day, [])):
                raise ValueError("A manual lesson conflicts with a school break")
            blocked.setdefault(day, []).append((begin, end))
            key = (slot.teacher_id, slot.subject_id)
            covered_minutes[key] = covered_minutes.get(key, 0) + end - begin
        assignments = []
        for a in assignments_data:
            key = (a["teacher_id"], a["subject_id"])
            remaining = a["hours_per_week"] * 60 - covered_minutes.pop(key, 0)
            if remaining < 0:
                raise ValueError("Manual lessons exceed the subject's weekly quota")
            assignments.append(
                Assignment(
                    teacher_id=a["teacher_id"],
                    subject_id=a["subject_id"],
                    hours_per_week=a["hours_per_week"],
                    minutes_per_week=remaining,
                )
            )
        if covered_minutes:
            raise ValueError("A manual lesson is no longer assigned to its teacher and subject")
        from math import gcd

        # A 90-minute manual lesson may leave a 30-minute quota. Work in the
        # greatest exact common granularity rather than round 30 minutes away.
        quantum = slot_duration_minutes
        for assignment in assignments:
            remaining = assignment.minutes_per_week or 0
            if remaining:
                quantum = gcd(quantum, remaining)
        grid_blocks = build_blocks(day_names, day_start_hour, day_end_hour, quantum, blocked)

        # Load teacher unavailabilities from DB
        teacher_unavailabilities: dict[int, set[int]] = {}
        unique_teachers = {a["teacher_id"] for a in assignments_data}

        for tid in unique_teachers:
            blocked = await repo.get_unavailable_block_indices(db, tid, grid_blocks)
            if blocked:
                teacher_unavailabilities[tid] = blocked

        # Fresh cross-class availability, using the exact break-adjusted times.
        for tid in unique_teachers:
            cross = await repo.get_cross_class_blocked_block_indices(
                db,
                tid,
                class_id,
                grid_blocks,
                academic_year_id=academic_year_id,
            )
            teacher_unavailabilities[tid] = teacher_unavailabilities.get(tid, set()) | cross
        pref = {}
        for tid in unique_teachers:
            pref[tid] = await repo.get_preferred_block_indices(db, tid, grid_blocks)

        # Solve
        gen_result = solve(
            assignments=assignments,
            blocks=grid_blocks,
            slot_duration_minutes=quantum,
            teacher_unavailabilities=teacher_unavailabilities,
            preferred_blocks=pref if pref else None,
        )
        if not gen_result.feasible:
            raise ValueError(
                "OR-Tools: aucun emploi du temps faisable avec les contraintes donnees"
            )

        # Failed solves leave the previous generated schedule untouched.
        # Replace the auto-generated slots only after a feasible result exists.
        await db.execute(
            delete(TimetableSlot).where(
                TimetableSlot.class_id == class_id,
                TimetableSlot.academic_year_id == academic_year_id,
                TimetableSlot.timetable_id.is_not(None),
            )
        )
        await db.flush()

        # Create timetable header
        timetable = await repo.create_timetable(
            db, class_id=class_id, academic_year_id=academic_year_id
        )

        # Manual courses are excluded from the grid. The solver only returns
        # the remaining teaching minutes, so no manual course is duplicated.
        new_merged = gen_result.merged_slots

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
