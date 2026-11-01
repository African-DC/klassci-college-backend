"""Generation d'un emploi du temps de classe, dans une seule transaction.

Ordre des verrous : la classe, puis les enseignants triés, puis la salle.
Le solveur tourne avant tout remplacement : un échec laisse le planning intact,
et le commit est la dernière étape.
"""

from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.academic import Class, Room, Subject
from app.models.timetable import TimetableSlot
from app.models.user import TeacherProfile
from app.repositories import timetable_repository as repo
from app.services import schedule_event_service
from app.utils.timetable_days import JOURS_FR, day_value
from app.utils.timetable_generator import (
    MAX_SOLVER_SECONDS,
    Assignment,
    GeneratorResult,
    MergedSlot,
    SlotBlock,
    build_blocks,
    plan_assignments,
    solve,
)

_PLANNING_CONSERVE = "Le planning précédent est conservé."


class TimetableGenerationError(Exception):
    """A generation refusal whose message is written for the school administrator."""


@dataclass(frozen=True)
class GridSettings:
    day_names: list[str]
    day_start_hour: int
    day_end_hour: int
    slot_duration_minutes: int


@dataclass
class ClassWeek:
    """Breaks, school events and manual lessons of one class for one academic year."""

    blocked: dict[str, list[tuple[int, int]]]
    manual: list[TimetableSlot]


async def load_class_week(db: AsyncSession, class_id: int, academic_year_id: int) -> ClassWeek:
    events = await schedule_event_service.list_events(
        db, academic_year_id=academic_year_id, class_id=class_id
    )
    manual = await repo.list_manual_slots_for_class(db, class_id, academic_year_id=academic_year_id)
    return ClassWeek(
        blocked=schedule_event_service.to_blocked_periods(events, class_id),
        manual=manual,
    )


def manual_interval(slot: TimetableSlot) -> tuple[str, int, int]:
    """Day, start and end in minutes of a manual lesson."""
    begin = slot.start_time.hour * 60 + slot.start_time.minute
    end = slot.end_time.hour * 60 + slot.end_time.minute
    return day_value(slot.day), begin, end


def place_manual_lessons(week: ClassWeek) -> dict[tuple[int, int], int]:
    """Check manual lessons against breaks, block their minutes, count them per subject."""
    covered: dict[tuple[int, int], int] = {}
    for slot in week.manual:
        day, begin, end = manual_interval(slot)
        if end <= begin:
            raise TimetableGenerationError(
                f"Le cours manuel du {_jour_et_plage(day, slot)} a une durée invalide. "
                f"{_PLANNING_CONSERVE}"
            )
        if any(a < end and b > begin for a, b in week.blocked.get(day, [])):
            raise TimetableGenerationError(
                f"Le cours manuel du {_jour_et_plage(day, slot)} chevauche une pause. "
                f"Déplacez-le, puis relancez la génération. {_PLANNING_CONSERVE}"
            )
        week.blocked.setdefault(day, []).append((begin, end))
        key = (slot.teacher_id, slot.subject_id)
        covered[key] = covered.get(key, 0) + end - begin
    return covered


async def required_assignments(
    db: AsyncSession,
    assignments_data: list[dict[str, Any]],
    covered: dict[tuple[int, int], int],
) -> list[Assignment]:
    """Minutes each subject still needs once manual lessons are placed."""
    required: list[Assignment] = []
    exceeded: list[tuple[int, int, int]] = []
    for a in assignments_data:
        key = (a["teacher_id"], a["subject_id"])
        weekly = a["hours_per_week"] * 60
        remaining = weekly - covered.pop(key, 0)
        if remaining < 0:
            exceeded.append((a["subject_id"], weekly - remaining, weekly))
            continue
        required.append(
            Assignment(
                teacher_id=a["teacher_id"],
                subject_id=a["subject_id"],
                minutes_per_week=remaining,
            )
        )
    if exceeded or covered:
        refusal = await _manual_lessons_refusal(db, exceeded, {s for _, s in covered})
        raise TimetableGenerationError(refusal)
    return required


async def acquire_generation_locks(
    db: AsyncSession, class_id: int, teacher_ids: set[int], room_id: int | None
) -> None:
    """Serialize jobs sharing a class, a teacher or the room, always in this order."""
    await repo.lock_rows(db, Class, [class_id])
    await repo.lock_rows(db, TeacherProfile, teacher_ids)
    await repo.lock_rows(db, Room, [] if room_id is None else [room_id])


async def build_grid(
    db: AsyncSession,
    week: ClassWeek,
    class_id: int,
    academic_year_id: int,
    room_id: int | None,
    settings: GridSettings,
) -> list[SlotBlock]:
    """Grid of the class, interrupted by breaks, manual lessons and the room's other classes."""
    if room_id is not None:
        busy = await repo.get_room_busy_periods(db, room_id, class_id, academic_year_id)
        for day, periods in busy.items():
            week.blocked.setdefault(day, []).extend(periods)
    return build_blocks(
        settings.day_names,
        settings.day_start_hour,
        settings.day_end_hour,
        settings.slot_duration_minutes,
        week.blocked,
    )


async def solve_week(
    db: AsyncSession,
    assignments: list[Assignment],
    grid: list[SlotBlock],
    teacher_ids: set[int],
    class_id: int,
    academic_year_id: int,
    settings: GridSettings,
) -> GeneratorResult:
    unavailable = await _teacher_unavailability(db, teacher_ids, class_id, academic_year_id, grid)
    preferred = {tid: await repo.get_preferred_block_indices(db, tid, grid) for tid in teacher_ids}
    result = solve(
        assignments=assignments,
        blocks=grid,
        slot_duration_minutes=settings.slot_duration_minutes,
        teacher_unavailabilities=unavailable,
        preferred_blocks=preferred or None,
    )
    if result.timed_out:
        raise TimetableGenerationError(
            f"Le calcul n'a pas abouti dans le temps imparti ({MAX_SOLVER_SECONDS:.0f} s), "
            "ce qui ne signifie pas qu'aucun emploi du temps n'existe. Réessayez, ou "
            f"réduisez les contraintes de cette classe. {_PLANNING_CONSERVE}"
        )
    if not result.feasible:
        raise TimetableGenerationError(
            "Aucun emploi du temps ne respecte toutes les contraintes : volume horaire, "
            "pauses, cours manuels et disponibilités des enseignants et de la salle. "
            f"{_PLANNING_CONSERVE}"
        )
    return result


async def _teacher_unavailability(
    db: AsyncSession,
    teacher_ids: set[int],
    class_id: int,
    academic_year_id: int,
    grid: list[SlotBlock],
) -> dict[int, set[int]]:
    """Blocks where a teacher is away or already teaching in another class."""
    unavailable: dict[int, set[int]] = {}
    for tid in teacher_ids:
        own = await repo.get_unavailable_block_indices(db, tid, grid)
        cross = await repo.get_cross_class_blocked_block_indices(
            db, tid, class_id, grid, academic_year_id=academic_year_id
        )
        if own or cross:
            unavailable[tid] = own | cross
    return unavailable


async def replace_generated_slots(db: AsyncSession, class_id: int, academic_year_id: int) -> None:
    """Remove the auto-generated slots, only once a feasible result exists."""
    await db.execute(
        delete(TimetableSlot).where(
            TimetableSlot.class_id == class_id,
            TimetableSlot.academic_year_id == academic_year_id,
            TimetableSlot.timetable_id.is_not(None),
        )
    )
    await db.flush()


async def persist_schedule(
    db: AsyncSession,
    *,
    class_id: int,
    academic_year_id: int,
    room_id: int | None,
    assignments: list[Assignment],
    merged: list[MergedSlot],
) -> list[TimetableSlot]:
    timetable = await repo.create_timetable(
        db, class_id=class_id, academic_year_id=academic_year_id
    )
    rows = [
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
        for ms in merged
    ]
    return await repo.create_slots_bulk(db, rows, timetable.id)


async def build_response(
    db: AsyncSession,
    *,
    class_id: int,
    academic_year_id: int,
    created: list[TimetableSlot],
    unplanned: list[tuple[int, int]],
) -> dict[str, Any]:
    """Generated lessons plus the manual lessons of the same academic year."""
    slot_responses = []
    for slot in created:
        refreshed = await repo.get_slot_by_id(db, slot.id)
        if refreshed:
            slot_responses.append(_slot_to_dict(refreshed))
    manual = await repo.list_manual_slots_for_class(db, class_id, academic_year_id=academic_year_id)
    slot_responses.extend(_slot_to_dict(ms) for ms in manual)
    result: dict[str, Any] = {"slots": slot_responses}
    if unplanned:
        result["warning"] = await _unplanned_warning(db, unplanned)
    return result


async def generate_class_timetable(
    db: AsyncSession,
    *,
    class_id: int,
    academic_year_id: int,
    assignments_data: list[dict[str, Any]],
    room_id: int | None,
    settings: GridSettings,
) -> dict[str, Any]:
    """Regenerate a class timetable inside the caller's transaction, committing last."""
    if not assignments_data:
        raise TimetableGenerationError(
            f"Aucune matière à planifier pour cette classe. {_PLANNING_CONSERVE}"
        )
    teacher_ids = {a["teacher_id"] for a in assignments_data}
    await acquire_generation_locks(db, class_id, teacher_ids, room_id)
    week = await load_class_week(db, class_id, academic_year_id)
    covered = place_manual_lessons(week)
    required = await required_assignments(db, assignments_data, covered)
    assignments, unplanned = plan_assignments(required, settings.slot_duration_minutes)
    grid = await build_grid(db, week, class_id, academic_year_id, room_id, settings)
    result = await solve_week(
        db, assignments, grid, teacher_ids, class_id, academic_year_id, settings
    )
    await replace_generated_slots(db, class_id, academic_year_id)
    created = await persist_schedule(
        db,
        class_id=class_id,
        academic_year_id=academic_year_id,
        room_id=room_id,
        assignments=assignments,
        merged=result.merged_slots,
    )
    response = await build_response(
        db,
        class_id=class_id,
        academic_year_id=academic_year_id,
        created=created,
        unplanned=unplanned,
    )
    # Last step: any failure above rolls back, so "schedule kept" stays true.
    await db.commit()
    return response


def _jour_et_plage(day: str, slot: TimetableSlot) -> str:
    begin, end = slot.start_time.strftime("%H:%M"), slot.end_time.strftime("%H:%M")
    return f"{JOURS_FR.get(day, day)} de {begin} à {end}"


async def _subject_names(db: AsyncSession, subject_ids: set[int]) -> dict[int, str]:

    rows = await db.execute(select(Subject.id, Subject.name).where(Subject.id.in_(subject_ids)))
    return {row.id: row.name for row in rows}


def _duree(minutes: int) -> str:
    hours, rest = divmod(minutes, 60)
    if not hours:
        return f"{rest} min"
    return f"{hours} h {rest:02d}" if rest else f"{hours} h"


async def _manual_lessons_refusal(
    db: AsyncSession, exceeded: list[tuple[int, int, int]], orphans: set[int]
) -> str:
    """Say which subjects to correct, since the fix is in the administrator's hands."""
    names = await _subject_names(db, {subject for subject, _, _ in exceeded} | orphans)
    parts = []
    if exceeded:
        details = ", ".join(
            f"{names.get(subject, 'une matière')} ({_duree(manual)} posées pour {_duree(weekly)})"
            for subject, manual, weekly in exceeded
        )
        parts.append(f"Les cours manuels dépassent le volume horaire : {details}.")
    if orphans:
        details = ", ".join(sorted(names.get(subject, "une matière") for subject in orphans))
        parts.append(f"Des cours manuels n'ont plus le bon enseignant : {details}.")
    return f"{' '.join(parts)} Corrigez-les, puis relancez la génération. {_PLANNING_CONSERVE}"


async def _unplanned_warning(db: AsyncSession, unplanned: list[tuple[int, int]]) -> str:
    """Name the minutes too short to be scheduled as a lesson of their own."""
    names = await _subject_names(db, {subject_id for subject_id, _ in unplanned})
    details = ", ".join(f"{names.get(sid, 'une matière')} ({mins} min)" for sid, mins in unplanned)
    return f"Trop court pour faire un cours, à répartir à la main : {details}."


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
        "day": day_value(slot.day),
        "start_time": slot.start_time.strftime("%H:%M"),
        "end_time": slot.end_time.strftime("%H:%M"),
        "room": slot.room.name if slot.room else None,
    }
