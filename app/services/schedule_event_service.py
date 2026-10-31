"""Business rules for recurring school breaks and special sessions."""

from datetime import time

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditAction, audit_log
from app.core.exceptions import BusinessValidationError, ConflictError, NotFoundError
from app.models.academic import AcademicYear, Class
from app.models.timetable import ScheduleEvent, TimetableSlot
from app.schemas.schedule_event import ScheduleEventCreate, ScheduleEventResponse


def _overlap(model, day: str, start: time, end: time):
    return (
        model.day == day,
        model.start_time < end,
        model.end_time > start,
    )


async def lock_class_scope(db: AsyncSession, class_id: int | None) -> None:
    """Serialize schedule mutations with generation for affected classes."""
    stmt = select(Class.id).order_by(Class.id).with_for_update()
    if class_id is not None:
        stmt = stmt.where(Class.id == class_id)
    await db.execute(stmt)


async def list_events(db: AsyncSession, *, academic_year_id: int, class_id: int | None = None):
    stmt = select(ScheduleEvent).where(ScheduleEvent.academic_year_id == academic_year_id)
    if class_id is not None:
        stmt = stmt.where(
            or_(
                ScheduleEvent.class_id.is_(None),
                ScheduleEvent.class_id == class_id,
            )
        )
    stmt = stmt.order_by(ScheduleEvent.day, ScheduleEvent.start_time)
    return list((await db.execute(stmt)).scalars().all())


async def _validate_scope(db: AsyncSession, data: ScheduleEventCreate):
    year_stmt = select(AcademicYear.id).where(AcademicYear.id == data.academic_year_id)
    if not (await db.execute(year_stmt)).scalar_one_or_none():
        raise NotFoundError("AcademicYear", data.academic_year_id)
    if data.class_id is not None:
        class_stmt = select(Class.id).where(Class.id == data.class_id)
        if not (await db.execute(class_stmt)).scalar_one_or_none():
            raise NotFoundError("Class", data.class_id)


async def ensure_course_allowed(
    db: AsyncSession,
    *,
    class_id: int,
    academic_year_id: int,
    day: str,
    start: time,
    end: time,
) -> None:
    stmt = (
        select(ScheduleEvent.id)
        .where(
            ScheduleEvent.academic_year_id == academic_year_id,
            ScheduleEvent.blocks_courses.is_(True),
            or_(
                ScheduleEvent.class_id.is_(None),
                ScheduleEvent.class_id == class_id,
            ),
            *_overlap(ScheduleEvent, day, start, end),
        )
        .limit(1)
    )
    if (await db.execute(stmt)).first():
        raise ConflictError(
            "Ce créneau chevauche une pause ou une activité bloquante de la classe."
        )


async def _check_event_conflicts(
    db: AsyncSession, data: ScheduleEventCreate, event_id: int | None = None
):
    if not data.blocks_courses:
        return
    q = select(ScheduleEvent.id).where(
        ScheduleEvent.academic_year_id == data.academic_year_id,
        ScheduleEvent.blocks_courses.is_(True),
        *_overlap(ScheduleEvent, data.day.value, data.start_time, data.end_time),
    )
    if data.class_id is not None:
        q = q.where(
            or_(
                ScheduleEvent.class_id.is_(None),
                ScheduleEvent.class_id == data.class_id,
            )
        )
    if event_id is not None:
        q = q.where(ScheduleEvent.id != event_id)
    if (await db.execute(q.limit(1))).first():
        raise ConflictError("Cette période chevauche une autre pause bloquante.")

    lessons = select(TimetableSlot.id).where(
        TimetableSlot.academic_year_id == data.academic_year_id,
        *_overlap(TimetableSlot, data.day.value, data.start_time, data.end_time),
    )
    if data.class_id is not None:
        lessons = lessons.where(TimetableSlot.class_id == data.class_id)
    if (await db.execute(lessons.limit(1))).first():
        raise ConflictError(
            "Un cours existe déjà pendant cette période. "
            "Déplacez ce cours avant d'ajouter la pause."
        )


async def save_event(
    db: AsyncSession,
    data: ScheduleEventCreate,
    actor: int,
    event_id: int | None = None,
):
    await _validate_scope(db, data)
    await lock_class_scope(db, data.class_id)
    event = await db.get(ScheduleEvent, event_id) if event_id is not None else None
    if event_id is not None and event is None:
        raise NotFoundError("ScheduleEvent", event_id)
    await _check_event_conflicts(db, data, event_id)
    before = (
        None
        if event is None
        else {
            "title": event.title,
            "start_time": str(event.start_time),
            "end_time": str(event.end_time),
        }
    )
    if event is None:
        event = ScheduleEvent(**data.model_dump())
        db.add(event)
    else:
        for key, value in data.model_dump().items():
            setattr(event, key, value)
    await db.flush()
    await audit_log(
        db,
        entity_type="schedule_event",
        action=AuditAction.UPDATE if event_id is not None else AuditAction.CREATE,
        user_id=actor,
        entity_id=event.id,
        old_values=before,
        new_values=data.model_dump(mode="json"),
    )
    await db.commit()
    await db.refresh(event)
    return ScheduleEventResponse.model_validate(event)


async def remove_event(db: AsyncSession, event_id: int, actor: int):
    event = await db.get(ScheduleEvent, event_id)
    if event is None:
        raise NotFoundError("ScheduleEvent", event_id)
    await lock_class_scope(db, event.class_id)
    await audit_log(
        db,
        entity_type="schedule_event",
        action=AuditAction.DELETE,
        user_id=actor,
        entity_id=event.id,
        old_values={
            "title": event.title,
            "academic_year_id": event.academic_year_id,
        },
    )
    await db.delete(event)
    await db.commit()


def blocked_indices(events: list[ScheduleEvent], grid_blocks: list, class_id: int) -> set[int]:
    """Exclude any solver block overlapping a blocking period."""
    result = set()
    for block in grid_blocks:
        for event in events:
            if not event.blocks_courses or (
                event.class_id is not None and event.class_id != class_id
            ):
                continue
            start = event.start_time.hour * 60 + event.start_time.minute
            end = event.end_time.hour * 60 + event.end_time.minute
            if event.day == block.day and block.start_minutes < end and block.end_minutes > start:
                result.add(block.index)
                break
    return result


def to_blocked_periods(
    events: list[ScheduleEvent], class_id: int
) -> dict[str, list[tuple[int, int]]]:
    """Convert blocking periods to exact day intervals for the scheduler."""
    periods: dict[str, list[tuple[int, int]]] = {}
    for event in events:
        if not event.blocks_courses or (event.class_id is not None and event.class_id != class_id):
            continue
        day = event.day.value if hasattr(event.day, "value") else event.day
        start = event.start_time.hour * 60 + event.start_time.minute
        end = event.end_time.hour * 60 + event.end_time.minute
        periods.setdefault(day, []).append((start, end))
    return periods


async def save_events_bulk(
    db: AsyncSession, events: list[ScheduleEventCreate], actor: int
) -> list[ScheduleEventResponse]:
    """Validate ALL days before inserting; never leave a partial school week."""
    if not events or len(events) > 60:
        raise BusinessValidationError("Sélectionnez entre 1 et 60 périodes à créer.")
    # Lock every affected classroom in deterministic order before validation.
    scopes = {item.class_id for item in events}
    if None in scopes:
        await lock_class_scope(db, None)
    else:
        for class_id in sorted(scopes):
            await lock_class_scope(db, class_id)
    for index, value in enumerate(events):
        await _validate_scope(db, value)
        await _check_event_conflicts(db, value)
        for previous in events[:index]:
            if (
                value.academic_year_id == previous.academic_year_id
                and value.day == previous.day
                and value.blocks_courses
                and previous.blocks_courses
                and (
                    value.class_id is None
                    or previous.class_id is None
                    or value.class_id == previous.class_id
                )
                and value.start_time < previous.end_time
                and value.end_time > previous.start_time
            ):
                raise ConflictError("Les périodes demandées se chevauchent.")
    results = []
    for value in events:
        event = ScheduleEvent(**value.model_dump())
        db.add(event)
        await db.flush()
        await audit_log(
            db,
            entity_type="schedule_event",
            action=AuditAction.CREATE,
            user_id=actor,
            entity_id=event.id,
            new_values=value.model_dump(mode="json"),
        )
        results.append(ScheduleEventResponse.model_validate(event))
    await db.commit()
    return results
