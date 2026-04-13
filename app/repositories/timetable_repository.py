"""Repository emploi du temps — accès DB pour TimetableSlot et TeacherAvailability."""

from datetime import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.academic import Room
from app.models.timetable import TeacherAvailability, Timetable, TimetableSlot

# ---------------------------------------------------------------------------
# TimetableSlot — lecture
# ---------------------------------------------------------------------------


def _slot_load_options() -> list[Any]:
    """Options selectinload communes pour charger les relations d'un slot."""
    return [
        selectinload(TimetableSlot.class_),
        selectinload(TimetableSlot.teacher),
        selectinload(TimetableSlot.subject),
        selectinload(TimetableSlot.room),
    ]


async def get_slot_by_id(db: AsyncSession, slot_id: int) -> TimetableSlot | None:
    """Retourne un créneau par ID avec ses relations chargées."""
    stmt = select(TimetableSlot).where(TimetableSlot.id == slot_id).options(*_slot_load_options())
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_slots(
    db: AsyncSession,
    *,
    class_id: int | None = None,
    teacher_id: int | None = None,
    academic_year_id: int | None = None,
) -> list[TimetableSlot]:
    """Liste les créneaux avec filtres optionnels."""
    stmt = select(TimetableSlot).options(*_slot_load_options())
    if class_id is not None:
        stmt = stmt.where(TimetableSlot.class_id == class_id)
    if teacher_id is not None:
        stmt = stmt.where(TimetableSlot.teacher_id == teacher_id)
    if academic_year_id is not None:
        stmt = stmt.where(TimetableSlot.academic_year_id == academic_year_id)
    stmt = stmt.order_by(TimetableSlot.day, TimetableSlot.start_time)
    return list((await db.execute(stmt)).scalars().all())


# ---------------------------------------------------------------------------
# TimetableSlot — écriture
# ---------------------------------------------------------------------------


async def check_teacher_conflict(
    db: AsyncSession,
    teacher_id: int,
    day: str,
    start_time: time,
    end_time: time,
    exclude_slot_id: int | None = None,
) -> bool:
    """Retourne True si l'enseignant est déjà occupé sur ce créneau."""
    stmt = select(TimetableSlot).where(
        TimetableSlot.teacher_id == teacher_id,
        TimetableSlot.day == day,
        TimetableSlot.start_time < end_time,
        TimetableSlot.end_time > start_time,
    )
    if exclude_slot_id is not None:
        stmt = stmt.where(TimetableSlot.id != exclude_slot_id)
    result = (await db.execute(stmt)).scalar_one_or_none()
    return result is not None


async def check_class_conflict(
    db: AsyncSession,
    class_id: int,
    day: str,
    start_time: time,
    end_time: time,
    exclude_slot_id: int | None = None,
) -> bool:
    """Retourne True si la classe a déjà un cours sur ce créneau."""
    stmt = select(TimetableSlot).where(
        TimetableSlot.class_id == class_id,
        TimetableSlot.day == day,
        TimetableSlot.start_time < end_time,
        TimetableSlot.end_time > start_time,
    )
    if exclude_slot_id is not None:
        stmt = stmt.where(TimetableSlot.id != exclude_slot_id)
    result = (await db.execute(stmt)).scalar_one_or_none()
    return result is not None


async def create_slot(
    db: AsyncSession,
    *,
    class_id: int,
    teacher_id: int,
    subject_id: int,
    academic_year_id: int,
    day: str,
    start_time: time,
    end_time: time,
    room_id: int | None,
    timetable_id: int | None = None,
) -> TimetableSlot:
    """Crée un créneau et flush pour obtenir l'ID."""
    slot = TimetableSlot(
        class_id=class_id,
        teacher_id=teacher_id,
        subject_id=subject_id,
        academic_year_id=academic_year_id,
        day=day,
        start_time=start_time,
        end_time=end_time,
        room_id=room_id,
        timetable_id=timetable_id,
    )
    db.add(slot)
    await db.flush()
    return slot


UNSET: Any = object()  # sentinel pour distinguer "non fourni" vs "None explicite"
_UNSET = UNSET  # backward-compat alias


async def update_slot(
    db: AsyncSession,
    slot: TimetableSlot,
    *,
    teacher_id: int | None = None,
    subject_id: int | None = None,
    day: str | None = None,
    start_time: time | None = None,
    end_time: time | None = None,
    room_id: Any = _UNSET,
) -> TimetableSlot:
    """Met à jour les champs modifiables d'un créneau.

    room_id utilise un sentinel pour distinguer "non fourni" (pas de modification)
    de "None explicite" (suppression de la salle).
    """
    if teacher_id is not None:
        slot.teacher_id = teacher_id
    if subject_id is not None:
        slot.subject_id = subject_id
    if day is not None:
        slot.day = day
    if start_time is not None:
        slot.start_time = start_time
    if end_time is not None:
        slot.end_time = end_time
    if room_id is not _UNSET:
        slot.room_id = room_id
    await db.flush()
    return slot


async def delete_slot(db: AsyncSession, slot: TimetableSlot) -> None:
    """Supprime un créneau."""
    await db.delete(slot)
    await db.flush()


async def create_slots_bulk(
    db: AsyncSession,
    slots_data: list[dict[str, Any]],
    timetable_id: int,
) -> list[TimetableSlot]:
    """Crée plusieurs créneaux en lot (pour la génération OR-Tools)."""
    slots = []
    for data in slots_data:
        slot = TimetableSlot(
            class_id=data["class_id"],
            teacher_id=data["teacher_id"],
            subject_id=data["subject_id"],
            academic_year_id=data["academic_year_id"],
            day=data["day"],
            start_time=data["start_time"],
            end_time=data["end_time"],
            room_id=data.get("room_id"),
            timetable_id=timetable_id,
        )
        db.add(slot)
        slots.append(slot)
    await db.flush()
    return slots


# ---------------------------------------------------------------------------
# Timetable header
# ---------------------------------------------------------------------------


async def create_timetable(
    db: AsyncSession,
    *,
    class_id: int,
    academic_year_id: int,
) -> Timetable:
    """Crée un header d'emploi du temps."""
    timetable = Timetable(
        class_id=class_id,
        academic_year_id=academic_year_id,
        is_active=True,
    )
    db.add(timetable)
    await db.flush()
    return timetable


# ---------------------------------------------------------------------------
# Room
# ---------------------------------------------------------------------------


async def get_room_by_name(db: AsyncSession, name: str) -> Room | None:
    """Retourne une salle par son nom."""
    stmt = select(Room).where(Room.name == name)
    return (await db.execute(stmt)).scalar_one_or_none()


# ---------------------------------------------------------------------------
# TeacherAvailability
# ---------------------------------------------------------------------------


async def get_teacher_availability_by_id(
    db: AsyncSession, av_id: int
) -> TeacherAvailability | None:
    """Retourne une disponibilité par ID."""
    stmt = select(TeacherAvailability).where(TeacherAvailability.id == av_id)
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_teacher_availabilities(
    db: AsyncSession, teacher_id: int
) -> list[TeacherAvailability]:
    """Retourne toutes les disponibilités d'un enseignant."""
    stmt = (
        select(TeacherAvailability)
        .where(TeacherAvailability.teacher_id == teacher_id)
        .order_by(TeacherAvailability.day, TeacherAvailability.start_time)
    )
    return list((await db.execute(stmt)).scalars().all())


async def create_teacher_availability(
    db: AsyncSession,
    *,
    teacher_id: int,
    day: str,
    start_time: time,
    end_time: time,
    available: bool,
    preferred: bool = False,
) -> TeacherAvailability:
    """Crée une entrée de disponibilité enseignant."""
    av = TeacherAvailability(
        teacher_id=teacher_id,
        day=day,
        start_time=start_time,
        end_time=end_time,
        available=available,
        preferred=preferred,
    )
    db.add(av)
    await db.flush()
    return av


async def update_teacher_availability(
    db: AsyncSession,
    av: TeacherAvailability,
    *,
    available: bool | None = None,
    preferred: bool | None = None,
) -> TeacherAvailability:
    """Met à jour les champs d'une disponibilité enseignant."""
    if available is not None:
        av.available = available
    if preferred is not None:
        av.preferred = preferred
    db.add(av)
    await db.flush()
    return av


async def delete_teacher_availability(db: AsyncSession, av: TeacherAvailability) -> None:
    """Supprime une disponibilité enseignant."""
    await db.delete(av)
    await db.flush()


async def get_unavailable_slot_indices(
    db: AsyncSession,
    teacher_id: int,
    available_slots: list[dict[str, Any]],
) -> set[int]:
    """Retourne les indices des créneaux où l'enseignant est indisponible.

    Un créneau est considéré indisponible si une TeacherAvailability
    avec available=False le couvre (même jour + chevauchement horaire).
    """
    stmt = select(TeacherAvailability).where(
        TeacherAvailability.teacher_id == teacher_id,
        TeacherAvailability.available.is_(False),
    )
    unavailabilities = list((await db.execute(stmt)).scalars().all())

    blocked: set[int] = set()
    for idx, slot in enumerate(available_slots):
        slot_day = slot["day"]
        slot_start = slot["start_time"]
        slot_end = slot["end_time"]
        for unavail in unavailabilities:
            if (
                unavail.day == slot_day
                and unavail.start_time < slot_end
                and unavail.end_time > slot_start
            ):
                blocked.add(idx)
                break
    return blocked
