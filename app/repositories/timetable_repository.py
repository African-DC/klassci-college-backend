"""Repository emploi du temps — accès DB pour TimetableSlot et TeacherAvailability."""

from collections.abc import Iterable, Sequence
from datetime import time
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.academic import AcademicYear, Room
from app.models.enrollment import Enrollment, EnrollmentStatus
from app.models.timetable import TeacherAvailability, Timetable, TimetableSlot
from app.models.user import TeacherProfile
from app.utils.timetable_days import day_value
from app.utils.timetable_generator import SlotBlock

# ---------------------------------------------------------------------------
# Locks
# ---------------------------------------------------------------------------


async def lock_rows(db: AsyncSession, model: Any, ids: Iterable[int]) -> None:
    """Lock rows by id, in ascending id order. Callers lock families in a fixed order."""
    wanted = sorted(set(ids))
    if not wanted:
        return
    stmt = select(model.id).where(model.id.in_(wanted)).order_by(model.id).with_for_update()
    await db.execute(stmt)


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


async def get_enrollment_for_student_timetable(
    db: AsyncSession, student_id: int
) -> Enrollment | None:
    """The enrollment whose timetable a family should see today.

    A re-enrollment for next year is more recent but not yet in force: the
    current school year comes first, the latest enrollment only as a fallback.
    """
    stmt = (
        select(Enrollment)
        .join(Enrollment.academic_year)
        .where(
            Enrollment.student_id == student_id,
            Enrollment.status.not_in([EnrollmentStatus.ANNULE, EnrollmentStatus.REJETE]),
        )
        .options(selectinload(Enrollment.class_))
        .order_by(AcademicYear.is_current.desc(), Enrollment.id.desc())
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def find_room_conflict(
    db: AsyncSession,
    *,
    room_id: int,
    academic_year_id: int,
    day: str,
    start_time: time,
    end_time: time,
    exclude_slot_id: int | None = None,
) -> TimetableSlot | None:
    stmt = (
        select(TimetableSlot)
        .options(selectinload(TimetableSlot.class_))
        .where(
            TimetableSlot.room_id == room_id,
            TimetableSlot.academic_year_id == academic_year_id,
            TimetableSlot.day == day,
            TimetableSlot.start_time < end_time,
            TimetableSlot.end_time > start_time,
        )
    )
    if exclude_slot_id is not None:
        stmt = stmt.where(TimetableSlot.id != exclude_slot_id)
    return (await db.execute(stmt)).scalars().first()


async def get_room_busy_periods(
    db: AsyncSession,
    room_id: int,
    class_id: int,
    academic_year_id: int,
) -> dict[str, list[tuple[int, int]]]:
    """Day intervals, in minutes, when the room hosts another class in the year."""
    stmt = select(TimetableSlot).where(
        TimetableSlot.room_id == room_id,
        TimetableSlot.class_id != class_id,
        TimetableSlot.academic_year_id == academic_year_id,
    )
    busy: dict[str, list[tuple[int, int]]] = {}
    for slot in (await db.execute(stmt)).scalars().all():
        start = slot.start_time.hour * 60 + slot.start_time.minute
        end = slot.end_time.hour * 60 + slot.end_time.minute
        busy.setdefault(day_value(slot.day), []).append((start, end))
    return busy


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
    academic_year_id: int | None = None,
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
    if academic_year_id is not None:
        stmt = stmt.where(TimetableSlot.academic_year_id == academic_year_id)
    return (await db.execute(stmt)).scalars().first()


async def check_class_conflict(
    db: AsyncSession,
    class_id: int,
    day: str,
    start_time: time,
    end_time: time,
    exclude_slot_id: int | None = None,
    academic_year_id: int | None = None,
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
    if academic_year_id is not None:
        stmt = stmt.where(TimetableSlot.academic_year_id == academic_year_id)
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


def couvre_entierement(plages: Sequence[TeacherAvailability], debut: time, fin: time) -> bool:
    """Les plages ouvertes, mises bout a bout, couvrent-elles [debut, fin[ ?

    L'ecran de saisie des disponibilites est une grille d'heures : cocher
    « libre de 8 h a 12 h » ecrit quatre lignes d'une heure, jamais une ligne
    de quatre. Chercher UNE ligne qui couvre tout le creneau revenait donc a
    interdire les cours de plus d'une heure a tout enseignant qui s'etait
    declare disponible — l'exact contraire de ce qu'il venait de dire.

    On recolle donc ce qui se touche avant de mesurer. Un trou reste un trou :
    8h-9h et 10h-11h ne couvrent pas 8h-11h.
    """
    curseur = debut
    for plage in sorted(plages, key=lambda p: p.start_time):
        if plage.start_time > curseur:
            break
        curseur = max(curseur, plage.end_time)
        if curseur >= fin:
            return True
    return curseur >= fin


async def find_teacher_unavailability(
    db: AsyncSession,
    teacher_id: int,
    day: str,
    start_time: time,
    end_time: time,
) -> tuple[str, TeacherAvailability | None] | None:
    """Ce qui, dans les plages declarees, empeche ce creneau.

    La table se lit en liste blanche, exactement comme le generateur
    automatique la lit deja (`get_unavailable_block_indices`) et comme la grille
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

    ouvertes = list(
        (
            await db.execute(
                select(TeacherAvailability).where(
                    TeacherAvailability.teacher_id == teacher_id,
                    TeacherAvailability.day == day,
                    TeacherAvailability.available.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
    return None if couvre_entierement(ouvertes, start_time, end_time) else ("not_open", None)


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


async def list_manual_slots_for_class(
    db: AsyncSession,
    class_id: int,
    *,
    academic_year_id: int,
) -> list[TimetableSlot]:
    """Retourne les creneaux manuels (timetable_id IS NULL) d'une classe pour une annee."""
    stmt = (
        select(TimetableSlot)
        .where(
            TimetableSlot.class_id == class_id,
            TimetableSlot.academic_year_id == academic_year_id,
            TimetableSlot.timetable_id.is_(None),
        )
        .options(*_slot_load_options())
    )
    return list((await db.execute(stmt)).scalars().all())


# ---------------------------------------------------------------------------
# Block-based operations (for variable-duration solver)
# ---------------------------------------------------------------------------


async def get_unavailable_block_indices(
    db: AsyncSession,
    teacher_id: int,
    blocks: list[SlotBlock],
) -> set[int]:
    """Retourne les indices de blocs ou le prof est indisponible."""
    # Explicit closures block only their own intervals. Opening windows turn
    # the week into an allow-list, where adjacent entries count as continuous.
    has_open = await a_declare_des_ouvertures(db, teacher_id)
    entries = list(
        (
            await db.execute(
                select(TeacherAvailability).where(TeacherAvailability.teacher_id == teacher_id)
            )
        )
        .scalars()
        .all()
    )
    blocked: set[int] = set()
    for blk in blocks:
        start = time(blk.start_minutes // 60, blk.start_minutes % 60)
        end = time(blk.end_minutes // 60, blk.end_minutes % 60)
        day_entries = [a for a in entries if a.day == blk.day]
        if any(not a.available and a.start_time < end and a.end_time > start for a in day_entries):
            blocked.add(blk.index)
        elif has_open and not couvre_entierement(
            [a for a in day_entries if a.available], start, end
        ):
            blocked.add(blk.index)
    return blocked


async def get_preferred_block_indices(
    db: AsyncSession,
    teacher_id: int,
    blocks: list[SlotBlock],
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
    blocks: list[SlotBlock],
    academic_year_id: int | None = None,
) -> set[int]:
    """Block teacher overlaps in the requested academic year only."""
    stmt = select(TimetableSlot).where(
        TimetableSlot.teacher_id == teacher_id,
        TimetableSlot.class_id != exclude_class_id,
    )
    if academic_year_id is not None:
        stmt = stmt.where(TimetableSlot.academic_year_id == academic_year_id)
    existing = list((await db.execute(stmt)).scalars().all())

    blocked: set[int] = set()
    for blk in blocks:
        blk_start = time(blk.start_minutes // 60, blk.start_minutes % 60)
        blk_end = time(blk.end_minutes // 60, blk.end_minutes % 60)
        for ex in existing:
            if day_value(ex.day) == blk.day and ex.start_time < blk_end and ex.end_time > blk_start:
                blocked.add(blk.index)
                break
    return blocked
