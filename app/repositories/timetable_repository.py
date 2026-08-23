"""Repository emploi du temps — accès DB pour TimetableSlot et TeacherAvailability."""

from datetime import time
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.academic import Room
from app.models.timetable import TeacherAvailability, Timetable, TimetableSlot
from app.models.user import TeacherProfile

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


async def find_teacher_conflict(
    db: AsyncSession,
    teacher_id: int,
    day: str,
    start_time: time,
    end_time: time,
    exclude_slot_id: int | None = None,
) -> TimetableSlot | None:
    """Le cours qui occupe déjà l'enseignant sur ce créneau, s'il existe.

    Rend le créneau et non un booléen : un message qui dit « déjà occupé »
    sans dire par quoi oblige le secrétariat à ouvrir l'emploi du temps de
    chaque classe pour trouver lequel. La classe et la matière sont chargées
    ici, une fois, plutôt que relues par l'appelant.
    """
    stmt = (
        select(TimetableSlot)
        .options(
            selectinload(TimetableSlot.class_),
            selectinload(TimetableSlot.subject),
        )
        .where(
            TimetableSlot.teacher_id == teacher_id,
            TimetableSlot.day == day,
            TimetableSlot.start_time < end_time,
            TimetableSlot.end_time > start_time,
        )
    )
    if exclude_slot_id is not None:
        stmt = stmt.where(TimetableSlot.id != exclude_slot_id)
    return (await db.execute(stmt)).scalars().first()


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


async def get_teacher_profile(db: AsyncSession, teacher_id: int) -> TeacherProfile | None:
    """Le profil d'un enseignant — pour nommer quelqu'un dans un message."""
    stmt = select(TeacherProfile).where(TeacherProfile.id == teacher_id)
    return (await db.execute(stmt)).scalar_one_or_none()


async def a_declare_des_ouvertures(db: AsyncSession, teacher_id: int) -> bool:
    """L'enseignant a-t-il declare au moins une plage OUVERTE ?

    C'est cette question, et elle seule, qui fait basculer la table en liste
    blanche. Compter toutes les lignes serait un contresens : noter « absent
    mardi matin » fermerait alors les six jours, et le secretariat qui rend
    service en notant une absence rendrait l'enseignant inplacable.

    Une seule definition, lue par la creation manuelle et par le generateur
    automatique : les deux repondaient a la question separement, donc pouvaient
    y repondre differemment.
    """
    total = (
        await db.execute(
            select(func.count())
            .select_from(TeacherAvailability)
            .where(
                TeacherAvailability.teacher_id == teacher_id,
                TeacherAvailability.available.is_(True),
            )
        )
    ).scalar() or 0
    return total > 0


async def find_teacher_unavailability(
    db: AsyncSession,
    teacher_id: int,
    day: str,
    start_time: time,
    end_time: time,
) -> tuple[str, TeacherAvailability | None] | None:
    """Ce qui, dans les plages declarees, empeche ce creneau.

    La table se lit en liste blanche, exactement comme le generateur
    automatique la lit deja (`get_unavailable_slot_indices`) et comme la grille
    de la fiche enseignant l'affiche : tant qu'un enseignant n'a rien declare,
    il est reponse disponible partout ; des qu'il a declare quelque chose, seul
    ce qui est marque disponible l'est. Deux lectures differentes de la meme
    table donnaient une grille toute rouge et une creation pourtant acceptee.

    Renvoie `None` quand rien n'empeche, sinon le motif et la ligne en cause :
    « closed » pour une plage explicitement fermee, « not_open » quand le
    creneau tombe simplement hors de ce qui a ete ouvert. Les deux ne se disent
    pas pareil a l'ecran.
    """
    recouvre = (
        TeacherAvailability.start_time < end_time,
        TeacherAvailability.end_time > start_time,
    )

    fermeture = (
        (
            await db.execute(
                select(TeacherAvailability).where(
                    TeacherAvailability.teacher_id == teacher_id,
                    TeacherAvailability.day == day,
                    TeacherAvailability.available.is_(False),
                    *recouvre,
                )
            )
        )
        .scalars()
        .first()
    )
    if fermeture is not None:
        return "closed", fermeture

    if not await a_declare_des_ouvertures(db, teacher_id):
        return None

    couvert = (
        (
            await db.execute(
                select(TeacherAvailability).where(
                    TeacherAvailability.teacher_id == teacher_id,
                    TeacherAvailability.day == day,
                    TeacherAvailability.available.is_(True),
                    TeacherAvailability.start_time <= start_time,
                    TeacherAvailability.end_time >= end_time,
                )
            )
        )
        .scalars()
        .first()
    )
    return None if couvert is not None else ("not_open", None)


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
    """Retourne les indices des creneaux ou l'enseignant est indisponible.

    Un creneau est considere indisponible si AUCUNE TeacherAvailability
    avec available=True ne le couvre. Si le prof n'a declare aucune dispo,
    on suppose qu'il est disponible partout (pas de blocage).
    """
    # Check if teacher has ANY availability declarations
    if not await a_declare_des_ouvertures(db, teacher_id):
        # No declarations = teacher available everywhere
        return set()

    # Load available entries (available=True means teacher CAN work)
    stmt = select(TeacherAvailability).where(
        TeacherAvailability.teacher_id == teacher_id,
        TeacherAvailability.available.is_(True),
    )
    availabilities = list((await db.execute(stmt)).scalars().all())

    # Slots NOT covered by any available entry are blocked
    blocked: set[int] = set()
    for idx, slot in enumerate(available_slots):
        slot_day = slot["day"]
        slot_start = slot["start_time"]
        slot_end = slot["end_time"]
        is_available = False
        for avail in availabilities:
            if (
                avail.day == slot_day
                and avail.start_time <= slot_start
                and avail.end_time >= slot_end
            ):
                is_available = True
                break
        if not is_available:
            blocked.add(idx)
    return blocked


async def get_preferred_slot_indices(
    db: AsyncSession,
    teacher_id: int,
    available_slots: list,
) -> set[int]:
    """Retourne les indices des creneaux preferes par l'enseignant."""
    stmt = select(TeacherAvailability).where(
        TeacherAvailability.teacher_id == teacher_id,
        TeacherAvailability.preferred.is_(True),
    )
    preferred = list((await db.execute(stmt)).scalars().all())

    indices: set[int] = set()
    for idx, slot in enumerate(available_slots):
        slot_day = slot.day.value if hasattr(slot.day, "value") else slot["day"]
        slot_start = _to_time(
            slot.start_time if hasattr(slot, "start_time") else slot["start_time"]
        )
        slot_end = _to_time(slot.end_time if hasattr(slot, "end_time") else slot["end_time"])
        for pref in preferred:
            if pref.day == slot_day and pref.start_time <= slot_start and pref.end_time >= slot_end:
                indices.add(idx)
                break
    return indices


def _to_time(v: Any) -> time:
    """Convertit une str 'HH:MM' ou un datetime.time en time."""
    if isinstance(v, time):
        return v
    if isinstance(v, str):
        h, m = v.split(":")
        return time(int(h), int(m))
    return v


async def get_cross_class_blocked_slots(
    db: AsyncSession,
    teacher_id: int,
    exclude_class_id: int,
    available_slots: list,
) -> set[int]:
    """Retourne les indices des creneaux ou le prof est deja occupe dans une AUTRE classe."""
    stmt = select(TimetableSlot).where(
        TimetableSlot.teacher_id == teacher_id,
        TimetableSlot.class_id != exclude_class_id,
    )
    existing = list((await db.execute(stmt)).scalars().all())

    blocked: set[int] = set()
    for idx, slot in enumerate(available_slots):
        slot_day = slot.day.value if hasattr(slot.day, "value") else slot["day"]
        slot_start = _to_time(
            slot.start_time if hasattr(slot, "start_time") else slot["start_time"]
        )
        slot_end = _to_time(slot.end_time if hasattr(slot, "end_time") else slot["end_time"])
        for ex in existing:
            ex_day = ex.day if isinstance(ex.day, str) else ex.day
            if ex_day == slot_day and ex.start_time < slot_end and ex.end_time > slot_start:
                blocked.add(idx)
                break
    return blocked


async def list_manual_slots_for_class(
    db: AsyncSession,
    class_id: int,
) -> list[TimetableSlot]:
    """Retourne les creneaux manuels (timetable_id IS NULL) d'une classe."""
    stmt = (
        select(TimetableSlot)
        .where(TimetableSlot.class_id == class_id, TimetableSlot.timetable_id.is_(None))
        .options(*_slot_load_options())
    )
    return list((await db.execute(stmt)).scalars().all())


# ---------------------------------------------------------------------------
# Block-based operations (for variable-duration solver)
# ---------------------------------------------------------------------------


async def get_unavailable_block_indices(
    db: AsyncSession,
    teacher_id: int,
    blocks: list,
) -> set[int]:
    """Retourne les indices de blocs ou le prof est indisponible."""
    count_stmt = (
        select(func.count())
        .select_from(TeacherAvailability)
        .where(
            TeacherAvailability.teacher_id == teacher_id,
        )
    )
    total = (await db.execute(count_stmt)).scalar() or 0
    if total == 0:
        return set()

    stmt = select(TeacherAvailability).where(
        TeacherAvailability.teacher_id == teacher_id,
        TeacherAvailability.available.is_(True),
    )
    availabilities = list((await db.execute(stmt)).scalars().all())

    blocked: set[int] = set()
    for blk in blocks:
        blk_start = time(blk.start_minutes // 60, blk.start_minutes % 60)
        blk_end = time(blk.end_minutes // 60, blk.end_minutes % 60)
        is_available = False
        for avail in availabilities:
            if avail.day == blk.day and avail.start_time <= blk_start and avail.end_time >= blk_end:
                is_available = True
                break
        if not is_available:
            blocked.add(blk.index)
    return blocked


async def get_preferred_block_indices(
    db: AsyncSession,
    teacher_id: int,
    blocks: list,
) -> set[int]:
    """Retourne les indices de blocs preferes par le prof."""
    stmt = select(TeacherAvailability).where(
        TeacherAvailability.teacher_id == teacher_id,
        TeacherAvailability.preferred.is_(True),
    )
    preferred = list((await db.execute(stmt)).scalars().all())

    indices: set[int] = set()
    for blk in blocks:
        blk_start = time(blk.start_minutes // 60, blk.start_minutes % 60)
        blk_end = time(blk.end_minutes // 60, blk.end_minutes % 60)
        for pref in preferred:
            if pref.day == blk.day and pref.start_time <= blk_start and pref.end_time >= blk_end:
                indices.add(blk.index)
                break
    return indices


async def get_cross_class_blocked_block_indices(
    db: AsyncSession,
    teacher_id: int,
    exclude_class_id: int,
    blocks: list,
) -> set[int]:
    """Retourne les indices de blocs ou le prof est occupe dans une autre classe."""
    stmt = select(TimetableSlot).where(
        TimetableSlot.teacher_id == teacher_id,
        TimetableSlot.class_id != exclude_class_id,
    )
    existing = list((await db.execute(stmt)).scalars().all())

    blocked: set[int] = set()
    for blk in blocks:
        blk_start = time(blk.start_minutes // 60, blk.start_minutes % 60)
        blk_end = time(blk.end_minutes // 60, blk.end_minutes % 60)
        for ex in existing:
            ex_day = ex.day if isinstance(ex.day, str) else ex.day
            if ex_day == blk.day and ex.start_time < blk_end and ex.end_time > blk_start:
                blocked.add(blk.index)
                break
    return blocked
