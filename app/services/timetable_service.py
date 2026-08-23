"""Service emploi du temps — logique métier CRUD + génération OR-Tools."""

import logging
from datetime import time

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.audit import AuditAction, audit_log
from app.core.exceptions import BusinessValidationError, ConflictError, NotFoundError
from app.models.timetable import TimetableSlot
from app.repositories import timetable_repository as repo
from app.schemas.timetable import (
    GenerateTimetableRequest,
    GenerateTimetableResponse,
    TaskStatusResponse,
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


_JOURS_FR = {
    "monday": "lundi",
    "tuesday": "mardi",
    "wednesday": "mercredi",
    "thursday": "jeudi",
    "friday": "vendredi",
    "saturday": "samedi",
}


def _plage(debut: time, fin: time) -> str:
    return f"{debut.strftime('%H:%M')} à {fin.strftime('%H:%M')}"


async def _nom_enseignant(db: AsyncSession, teacher_id: int) -> str:
    """Le nom de l'enseignant, pour un message qu'un humain doit comprendre."""
    prof = await repo.get_teacher_profile(db, teacher_id)
    if prof is None:
        return f"L'enseignant #{teacher_id}"
    return f"{prof.first_name} {prof.last_name}".strip() or f"L'enseignant #{teacher_id}"


async def _verifier_enseignant_libre(
    db: AsyncSession,
    *,
    teacher_id: int,
    day: str,
    start: time,
    end: time,
    exclude_slot_id: int | None = None,
) -> None:
    """Refuse un créneau si l'enseignant est pris, en disant par quoi.

    Deux empêchements distincts, deux messages distincts : un cours déjà posé
    ailleurs se règle en déplaçant l'un des deux ; une indisponibilité que
    l'enseignant a déclarée lui-même se règle en lui parlant. « Créneau
    indisponible » obligeait le secrétariat à deviner lequel des deux.
    """
    jour = _JOURS_FR.get(day, day)

    conflit = await repo.find_teacher_conflict(
        db, teacher_id, day, start, end, exclude_slot_id=exclude_slot_id
    )
    if conflit is not None:
        nom = await _nom_enseignant(db, teacher_id)
        classe = conflit.class_.name if conflit.class_ else "une autre classe"
        matiere = conflit.subject.name if conflit.subject else "un cours"
        raise ConflictError(
            f"{nom} a déjà {matiere} avec la {classe} le {jour} de "
            f"{_plage(conflit.start_time, conflit.end_time)}."
        )

    empechement = await repo.find_teacher_unavailability(db, teacher_id, day, start, end)
    if empechement is not None:
        motif, plage_fermee = empechement
        nom = await _nom_enseignant(db, teacher_id)
        if motif == "closed" and plage_fermee is not None:
            raise ConflictError(
                f"{nom} est déclaré indisponible le {jour} de "
                f"{_plage(plage_fermee.start_time, plage_fermee.end_time)}."
            )
        raise ConflictError(
            f"{nom} n'est pas déclaré disponible le {jour} de {_plage(start, end)}. "
            "Ouvrez cette plage dans ses disponibilités si le cours doit y tenir."
        )


async def create_slot(
    db: AsyncSession,
    data: TimetableSlotCreate,
    created_by: int,
) -> TimetableSlotResponse:
    """Crée un créneau — vérifie les conflits d'abord."""
    start = _parse_time(data.start_time)
    end = _parse_time(data.end_time)

    if start >= end:
        raise BusinessValidationError("L'heure de fin doit être après l'heure de début.")

    # Résoudre la salle par nom si fourni
    room_id: int | None = None
    # Une chaine vide n'est pas un nom de salle : c'est « aucune salle », ce que
    # le formulaire envoie quand on choisit cette option. La modification le
    # savait deja ; la creation refusait le creneau avec « La salle « » n'existe
    # pas », donc poser un cours sans salle etait impossible.
    if data.room:
        room = await repo.get_room_by_name(db, data.room)
        if room is None:
            raise BusinessValidationError(f"La salle « {data.room} » n'existe pas.")
        room_id = room.id

    # Vérifier les conflits
    await _verifier_enseignant_libre(
        db, teacher_id=data.teacher_id, day=data.day.value, start=start, end=end
    )
    if await repo.check_class_conflict(db, data.class_id, data.day.value, start, end):
        raise ConflictError(
            f"Cette classe a déjà cours le {_JOURS_FR.get(data.day.value, data.day.value)} "
            f"de {_plage(start, end)}."
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
        raise BusinessValidationError("L'heure de fin doit être après l'heure de début.")

    # Résoudre la salle
    new_room_id: int | None
    if data.room is not None:
        if data.room == "":
            new_room_id = None
        else:
            room = await repo.get_room_by_name(db, data.room)
            if room is None:
                raise BusinessValidationError(f"La salle « {data.room} » n'existe pas.")
            new_room_id = room.id
    else:
        new_room_id = slot.room_id

    # Vérifier les conflits (en excluant le slot courant)
    await _verifier_enseignant_libre(
        db,
        teacher_id=new_teacher_id,
        day=new_day,
        start=new_start,
        end=new_end,
        exclude_slot_id=slot_id,
    )
    if await repo.check_class_conflict(
        db, slot.class_id, new_day, new_start, new_end, exclude_slot_id=slot_id
    ):
        raise ConflictError(
            f"Cette classe a déjà cours le {_JOURS_FR.get(new_day, new_day)} "
            f"de {_plage(new_start, new_end)}."
        )

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
    from sqlalchemy import func, or_, select

    from app.models.academic import Class, Subject

    cls = (await db.execute(select(Class).where(Class.id == class_id))).scalar_one_or_none()
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
            with_teacher.append(
                {
                    "id": s.id,
                    "name": s.name,
                    "hours_per_week": s.hours_per_week,
                    "teacher_id": s.teacher_id,
                    "teacher_name": f"{s.teacher.first_name} {s.teacher.last_name}",
                }
            )
        else:
            without_teacher.append(
                {
                    "id": s.id,
                    "name": s.name,
                    "hours_per_week": s.hours_per_week,
                }
            )

    # Count manual slots for this class
    manual_count_stmt = (
        select(func.count())
        .select_from(TimetableSlot)
        .where(TimetableSlot.class_id == class_id, TimetableSlot.timetable_id.is_(None))
    )
    manual_count = (await db.execute(manual_count_stmt)).scalar() or 0

    # Calculate total slots from settings
    slot_duration, start_h, end_h = await _get_timetable_settings(db)
    minutes_per_day = (end_h - start_h) * 60
    slots_per_day = minutes_per_day // slot_duration
    total_slots = 6 * slots_per_day

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


async def _get_timetable_settings(db: AsyncSession) -> tuple[int, int, int]:
    """Retourne (slot_duration_minutes, day_start_hour, day_end_hour) depuis SchoolSettings."""
    from sqlalchemy import select

    from app.models.academic import SchoolSettings

    stmt = select(SchoolSettings).limit(1)
    settings = (await db.execute(stmt)).scalar_one_or_none()
    if settings is None:
        return 60, 7, 17  # defaults
    return (
        settings.slot_duration_minutes or 60,
        settings.day_start_hour or 7,
        settings.day_end_hour or 17,
    )


async def auto_generate(
    db: AsyncSession,
    tenant_id: str,
    class_id: int,
) -> GenerateTimetableResponse:
    """Generation automatique intelligente avec granularite configurable.

    1. Lit les parametres de l'etablissement (duree bloc, heures debut/fin)
    2. Recupere la classe et ses matieres
    3. Verifie que TOUTES les matieres ont un enseignant
    4. Construit la grille de blocs dynamique
    5. Charge les slots manuels comme blocs fixes
    6. Charge les conflits inter-classes et preferences
    7. Supprime seulement les slots auto-generes
    8. Lance le solveur
    """
    from sqlalchemy import delete, or_, select

    from app.models.academic import AcademicYear, Class, Subject
    from app.models.timetable import DayOfWeek

    # 1. Settings
    slot_duration, day_start, day_end = await _get_timetable_settings(db)

    # 2. Get class
    cls = (await db.execute(select(Class).where(Class.id == class_id))).scalar_one_or_none()
    if cls is None:
        raise NotFoundError("Class", class_id)

    # Refactor #97 : Class est universel, l'AY pour le timetable est l'AY courante.
    current_ay = (
        await db.execute(select(AcademicYear).where(AcademicYear.is_current.is_(True)))
    ).scalar_one_or_none()
    if current_ay is None:
        raise BusinessValidationError("Aucune année académique courante configurée.")
    academic_year_id = current_ay.id

    # 3. Get subjects for this level
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

    without_teacher = [s for s in subjects if not s.teacher_id]
    if without_teacher:
        names = ", ".join(s.name for s in without_teacher)
        raise BusinessValidationError(
            f"Matieres sans enseignant : {names}. Utilisez le diagnostic pour les assigner."
        )

    # 4. Build assignments data for Celery
    assignments_data = [
        {"teacher_id": s.teacher_id, "subject_id": s.id, "hours_per_week": s.hours_per_week}
        for s in subjects
    ]

    # 5. Day names (English)
    day_names = [
        d.value
        for d in [
            DayOfWeek.MONDAY,
            DayOfWeek.TUESDAY,
            DayOfWeek.WEDNESDAY,
            DayOfWeek.THURSDAY,
            DayOfWeek.FRIDAY,
            DayOfWeek.SATURDAY,
        ]
    ]

    # 6. Delete only auto-generated slots
    del_stmt = delete(TimetableSlot).where(
        TimetableSlot.class_id == class_id,
        TimetableSlot.timetable_id.is_not(None),
    )
    await db.execute(del_stmt)
    await db.flush()

    # 7. Load manual slots — convert to block indices
    from app.utils.timetable_generator import build_blocks

    grid_blocks = build_blocks(day_names, day_start, day_end, slot_duration)

    manual_slots = await repo.list_manual_slots_for_class(db, class_id)
    manual_fixed_data = []
    for ms in manual_slots:
        ms_day = ms.day if isinstance(ms.day, str) else ms.day
        ms_start_min = ms.start_time.hour * 60 + ms.start_time.minute
        ms_end_min = ms.end_time.hour * 60 + ms.end_time.minute

        # Find assignment index
        asg_idx = None
        for idx, ad in enumerate(assignments_data):
            if ad["subject_id"] == ms.subject_id and ad["teacher_id"] == ms.teacher_id:
                asg_idx = idx
                break
        if asg_idx is None:
            continue

        # Find all blocks that this manual slot covers
        for blk in grid_blocks:
            if (
                blk.day == ms_day
                and blk.start_minutes >= ms_start_min
                and blk.end_minutes <= ms_end_min
            ):
                manual_fixed_data.append({"assignment_idx": asg_idx, "block_idx": blk.index})

    # 8. Cross-class conflicts — convert to block indices
    teacher_ids = {s.teacher_id for s in subjects}
    cross_class_blocked: dict[int, list[int]] = {}
    for tid in teacher_ids:
        blocked_indices = await repo.get_cross_class_blocked_block_indices(
            db,
            tid,
            class_id,
            grid_blocks,
        )
        if blocked_indices:
            cross_class_blocked[tid] = list(blocked_indices)

    # 9. Preferred blocks
    preferred_data: dict[int, list[int]] = {}
    for tid in teacher_ids:
        pref = await repo.get_preferred_block_indices(db, tid, grid_blocks)
        if pref:
            preferred_data[tid] = list(pref)

    await db.commit()

    # 10. Trigger Celery task
    from app.tasks.timetable_tasks import generate_timetable_task

    task = generate_timetable_task.delay(
        tenant_id,
        class_id,
        academic_year_id,
        assignments_data,
        day_names,
        day_start,
        day_end,
        slot_duration,
        cls.room_id,
        manual_fixed_data,
        {str(k): v for k, v in cross_class_blocked.items()},
        {str(k): v for k, v in preferred_data.items()},
    )
    return GenerateTimetableResponse(task_id=str(task.id))


def trigger_generate(
    tenant_id: str,
    request: GenerateTimetableRequest,
) -> GenerateTimetableResponse:
    """Dispatche la generation OR-Tools comme tache Celery (legacy endpoint)."""
    from app.tasks.timetable_tasks import generate_timetable_task

    task = generate_timetable_task.delay(
        tenant_id,
        request.class_id,
        request.academic_year_id,
        [
            {
                "teacher_id": a.teacher_id,
                "subject_id": a.subject_id,
                "hours_per_week": a.hours_per_week,
            }
            for a in request.assignments
        ],
        ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday"],
        7,
        17,
        60,  # defaults
        request.room_id,
        [],
        {},
        {},
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
# Timetable PDF export
# ---------------------------------------------------------------------------


async def export_timetable_pdf(db: AsyncSession, class_id: int) -> bytes:
    """Generate a PDF of the timetable for a class."""
    from sqlalchemy import select

    from app.models.academic import AcademicYear, Class, SchoolSettings
    from app.services.pdf_service import generate_timetable_pdf

    # Get class info
    cls = (await db.execute(select(Class).where(Class.id == class_id))).scalar_one_or_none()
    if cls is None:
        raise NotFoundError("Class", class_id)

    # Get current academic year
    ay = (
        await db.execute(select(AcademicYear).where(AcademicYear.is_current))
    ).scalar_one_or_none()
    academic_year_name = ay.name if ay else ""

    # Get school settings (full payload for PDF official header/footer)
    from app.services._school_settings_helper import load_school_settings_for_pdf

    settings = (await db.execute(select(SchoolSettings))).scalar_one_or_none()
    school_settings = await load_school_settings_for_pdf(db)
    day_start = settings.day_start_hour if settings else 7
    day_end = settings.day_end_hour if settings else 18

    # Get all slots for this class
    slots_raw = await repo.list_slots(db, class_id=class_id)
    slots_data = []
    for s in slots_raw:
        start_t = s.start_time if isinstance(s.start_time, str) else s.start_time.strftime("%H:%M")
        end_t = s.end_time if isinstance(s.end_time, str) else s.end_time.strftime("%H:%M")
        slots_data.append(
            {
                "day": s.day,
                "start_time": start_t,
                "end_time": end_t,
                "subject_name": s.subject.name if s.subject else "",
                "teacher_name": f"{s.teacher.last_name} {s.teacher.first_name}"
                if s.teacher
                else "",
                "room": s.room.name if s.room else None,
                "subject_color": s.subject.color
                if s.subject and hasattr(s.subject, "color")
                else None,
            }
        )

    class_name = cls.name
    return generate_timetable_pdf(
        slots=slots_data,
        class_name=class_name,
        academic_year=academic_year_name,
        school_settings=school_settings,
        day_start=day_start,
        day_end=day_end,
    )
