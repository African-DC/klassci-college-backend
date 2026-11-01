"""Génération : pas de cours de quelques minutes, et une cause d'échec lisible.

Ces tests rejouent les cas constatés sur le générateur : une pause à 10 h 10
sur une semaine chargée, un cours manuel qui laisse quelques minutes, et un
calcul qui n'aboutit pas. Ils exécutent le solveur et la tâche sur une vraie
base SQLite, puis lisent ce que l'administrateur recevrait.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import time
from typing import Any

import pytest
from ortools.sat.python import cp_model
from sqlalchemy import Integer, MetaData, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.academic import Class, Room, Subject
from app.models.timetable import DayOfWeek, ScheduleEvent, Timetable, TimetableSlot
from app.models.user import TeacherProfile
from app.services import schedule_event_service, timetable_generation, timetable_service
from app.services.pdf.timetable import _FALLBACK_CYCLE, _resolve_color
from app.tasks import timetable_tasks
from app.tasks.timetable_tasks import TimetableGenerationError, _generate_async
from app.utils.timetable_generator import (
    MIN_LESSON_MINUTES,
    Assignment,
    MergedSlot,
    build_blocks,
    join_adjacent_lessons,
    plan_assignments,
    solve,
)

SIX_DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday"]
YEAR = 2026
CLASS_ID = 10
TEACHER = 1
ENGLISH = 20


def _duration(slot: MergedSlot) -> int:
    return (slot.end_time.hour * 60 + slot.end_time.minute) - (
        slot.start_time.hour * 60 + slot.start_time.minute
    )


def _required(*minutes: int) -> list[Assignment]:
    return [
        Assignment(teacher_id=i, subject_id=i, minutes_per_week=m)
        for i, m in enumerate(minutes, start=1)
    ]


def _minutes_by_subject(result: Any, assignments: list[Assignment]) -> dict[int, int]:
    totals: dict[int, int] = {}
    for slot in result.merged_slots:
        subject = assignments[slot.assignment_idx].subject_id
        totals[subject] = totals.get(subject, 0) + _duration(slot)
    return totals


def test_a_loaded_week_with_a_10h10_break_has_no_ten_minute_lesson() -> None:
    blocked = {day: [(610, 625)] for day in SIX_DAYS}
    blocks = build_blocks(SIX_DAYS, 8, 17, 60, blocked)
    assert all(b.end_minutes - b.start_minutes >= MIN_LESSON_MINUTES for b in blocks)

    required = _required(600, 600, 600, 300, 300, 180)
    assignments, unplanned = plan_assignments(required, 60)
    result = solve(assignments, blocks, 60)

    assert result.feasible and not unplanned
    assert all(_duration(slot) >= MIN_LESSON_MINUTES for slot in result.merged_slots)
    assert _minutes_by_subject(result, assignments) == {
        1: 600,
        2: 600,
        3: 600,
        4: 300,
        5: 300,
        6: 180,
    }


def test_a_week_too_full_without_short_lessons_is_refused_rather_than_chopped() -> None:
    blocked = {"monday": [(610, 625)]}
    blocks = build_blocks(["monday"], 8, 11, 60, blocked)
    assert [(b.start_minutes, b.end_minutes) for b in blocks] == [
        (480, 540),
        (540, 600),
        (625, 660),
    ]

    assignments, _ = plan_assignments(_required(180), 60)
    assert not solve(assignments, blocks, 60).feasible


def test_a_90_minute_manual_lesson_does_not_shrink_the_grid_of_other_subjects() -> None:
    # 2 h - 1 h 30 manual: 30 minutes remain for this subject only.
    assignments, unplanned = plan_assignments(_required(30, 300, 240, 180, 120), 60)
    blocks = build_blocks(SIX_DAYS, 8, 17, 60)
    assert len(blocks) == 54

    result = solve(assignments, blocks, 60)

    assert result.feasible and not unplanned
    durations = [_duration(slot) for slot in result.merged_slots]
    assert durations.count(30) == 1
    assert all(d == 30 or d % 60 == 0 for d in durations)
    assert _minutes_by_subject(result, assignments)[1] == 30


@pytest.mark.parametrize(("manual", "left"), [(55, 5), (59, 1)])
def test_a_few_minutes_left_are_reported_and_never_become_a_lesson(manual: int, left: int) -> None:
    assignments, unplanned = plan_assignments(
        _required(60 - manual, 300, 240, 240, 180, 180, 120, 120, 60), 60
    )
    assert unplanned == [(1, left)]

    result = solve(assignments, build_blocks(SIX_DAYS, 8, 17, 60), 60)

    assert result.feasible and not result.timed_out
    assert all(_duration(slot) % 60 == 0 for slot in result.merged_slots)


def test_a_shorter_lesson_keeps_its_exact_duration_inside_its_block() -> None:
    assignments, _ = plan_assignments(_required(100), 60)
    result = solve(assignments, build_blocks(["monday"], 8, 12, 60), 60)

    assert result.feasible
    assert sorted(_duration(slot) for slot in result.merged_slots) == [40, 60]


def test_a_lesson_and_its_shorter_part_side_by_side_are_one_course() -> None:
    assignments, _ = plan_assignments(_required(90), 60)
    slots = [
        MergedSlot(0, "monday", time(8, 0), time(9, 0)),
        MergedSlot(1, "monday", time(9, 0), time(9, 30)),
    ]

    assert [_duration(slot) for slot in join_adjacent_lessons(slots, assignments)] == [90]


def test_two_subjects_side_by_side_stay_separate() -> None:
    assignments = _required(60, 60)
    slots = [
        MergedSlot(0, "monday", time(8, 0), time(9, 0)),
        MergedSlot(1, "monday", time(9, 0), time(10, 0)),
    ]

    assert len(join_adjacent_lessons(slots, assignments)) == 2


def test_reaching_the_time_limit_is_not_reported_as_impossible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cp_model.CpSolver, "solve", lambda *_: cp_model.UNKNOWN)
    result = solve(_required(60), build_blocks(["monday"], 8, 12, 60), 60)
    assert not result.feasible and result.timed_out


def test_a_solver_bug_is_not_reported_as_an_impossible_week(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cp_model.CpSolver, "solve", lambda *_: cp_model.MODEL_INVALID)
    with pytest.raises(RuntimeError):
        solve(_required(60), build_blocks(["monday"], 8, 12, 60), 60)


def test_a_really_impossible_week_is_not_reported_as_a_timeout() -> None:
    result = solve(_required(600), build_blocks(["monday"], 8, 10, 60), 60)
    assert not result.feasible and not result.timed_out


# --- La tâche, sur une vraie base ---


@pytest.fixture
async def session_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    mirror = MetaData()
    for table in Base.metadata.tables.values():
        table.to_metadata(mirror)
    names = (
        "classes",
        "subjects",
        "rooms",
        "teacher_profiles",
        "timetables",
        "timetable_slots",
        "schedule_events",
        "teacher_availabilities",
    )
    tables = [mirror.tables[name] for name in names]
    for table in tables:
        table.c.id.type = Integer()
    async with engine.begin() as conn:
        await conn.run_sync(lambda sync: mirror.create_all(sync, tables=tables))

    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as db:
        db.add_all(
            [
                Class(id=CLASS_ID, name="6eme A", level_id=1, series_id=None),
                Subject(id=ENGLISH, name="Anglais", coefficient=2),
                TeacherProfile(id=TEACHER, user_id=101, first_name="Yves", last_name="Koné"),
                Timetable(id=1, class_id=CLASS_ID, academic_year_id=YEAR),
            ]
        )
        await db.commit()

    @asynccontextmanager
    async def _session(_tenant: str) -> AsyncIterator[AsyncSession]:
        async with factory() as db:
            yield db

    monkeypatch.setattr(timetable_tasks, "_tenant_timetable_session", _session)
    yield factory
    await engine.dispose()


def _slot(start: time, end: time, *, generated: bool = False) -> TimetableSlot:
    return TimetableSlot(
        class_id=CLASS_ID,
        teacher_id=TEACHER,
        subject_id=ENGLISH,
        academic_year_id=YEAR,
        day=DayOfWeek.MONDAY,
        start_time=start,
        end_time=end,
        timetable_id=1 if generated else None,
    )


async def _generate(
    hours: int = 2, day_end_hour: int = 17, room_id: int | None = None
) -> dict[str, Any]:
    return await _generate_async(
        tenant_id="local",
        class_id=CLASS_ID,
        academic_year_id=YEAR,
        assignments_data=[{"teacher_id": TEACHER, "subject_id": ENGLISH, "hours_per_week": hours}],
        day_names=["monday"],
        day_start_hour=8,
        day_end_hour=day_end_hour,
        slot_duration_minutes=60,
        room_id=room_id,
    )


@pytest.mark.asyncio
async def test_a_55_minute_manual_lesson_names_the_minutes_left_over(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as db:
        db.add(_slot(time(8, 0), time(8, 55)))
        await db.commit()

    result = await _generate(hours=2)

    assert "Anglais (5 min)" in result["warning"]
    async with session_factory() as db:
        slots = list((await db.execute(select(TimetableSlot))).scalars().all())
    durations = sorted(
        (s.end_time.hour * 60 + s.end_time.minute) - (s.start_time.hour * 60 + s.start_time.minute)
        for s in slots
    )
    assert durations == [55, 60]


@pytest.mark.asyncio
async def test_an_empty_request_never_wipes_the_schedule(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as db:
        db.add(_slot(time(8, 0), time(9, 0), generated=True))
        await db.commit()

    with pytest.raises(TimetableGenerationError, match="Aucune matière à planifier"):
        await _generate_async(
            tenant_id="local",
            class_id=CLASS_ID,
            academic_year_id=YEAR,
            assignments_data=[],
            day_names=["monday"],
            day_start_hour=8,
            day_end_hour=17,
            slot_duration_minutes=60,
            room_id=None,
        )

    async with session_factory() as db:
        kept = list((await db.execute(select(TimetableSlot))).scalars().all())
    assert len(kept) == 1


@pytest.mark.asyncio
async def test_a_subject_fully_covered_by_manual_lessons_still_succeeds(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as db:
        db.add(_slot(time(8, 0), time(9, 0)))
        await db.commit()

    result = await _generate(hours=1)

    assert "warning" not in result
    async with session_factory() as db:
        slots = list((await db.execute(select(TimetableSlot))).scalars().all())
    assert [(s.start_time, s.timetable_id) for s in slots] == [(time(8, 0), None)]


@pytest.mark.asyncio
async def test_an_impossible_generation_explains_itself_and_keeps_the_schedule(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as db:
        db.add(_slot(time(8, 0), time(9, 0), generated=True))
        await db.commit()

    with pytest.raises(TimetableGenerationError, match="Le planning précédent est conservé"):
        await _generate(hours=5, day_end_hour=10)

    async with session_factory() as db:
        kept = list((await db.execute(select(TimetableSlot))).scalars().all())
    assert [(s.start_time, s.timetable_id) for s in kept] == [(time(8, 0), 1)]


@pytest.mark.asyncio
async def test_a_failure_while_finishing_saves_nothing(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail(*_args: object) -> str:
        raise RuntimeError("database gone")

    monkeypatch.setattr(timetable_generation, "_unplanned_warning", fail)
    async with session_factory() as db:
        db.add_all(
            [
                _slot(time(8, 0), time(8, 55)),
                _slot(time(9, 0), time(10, 0), generated=True),
            ]
        )
        await db.commit()

    with pytest.raises(RuntimeError):
        await _generate(hours=2)

    # The message says "schedule kept": it must be true at this exact point.
    async with session_factory() as db:
        kept = list((await db.execute(select(TimetableSlot))).scalars().all())
    assert sorted((s.start_time, s.timetable_id) for s in kept if s.timetable_id) == [
        (time(9, 0), 1)
    ]
    assert len(kept) == 2


@pytest.mark.asyncio
async def test_a_manual_lesson_over_quota_is_named_in_french(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as db:
        db.add(_slot(time(8, 0), time(11, 0)))
        await db.commit()

    with pytest.raises(TimetableGenerationError) as refusal:
        await _generate(hours=2)

    assert "Anglais (3 h posées pour 2 h)" in str(refusal.value)
    assert "Le planning précédent est conservé" in str(refusal.value)


@pytest.mark.asyncio
async def test_a_manual_lesson_with_another_teacher_names_the_subject(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    other = _slot(time(8, 0), time(9, 0))
    other.teacher_id = 99
    async with session_factory() as db:
        db.add(other)
        await db.commit()

    with pytest.raises(TimetableGenerationError, match="plus le bon enseignant : Anglais"):
        await _generate(hours=2)


@pytest.mark.asyncio
async def test_events_are_listed_from_monday_to_saturday(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as db:
        for day, start in (
            ("friday", time(10, 0)),
            ("saturday", time(10, 0)),
            ("monday", time(15, 0)),
            ("monday", time(10, 0)),
            ("wednesday", time(10, 0)),
        ):
            db.add(
                ScheduleEvent(
                    academic_year_id=YEAR,
                    class_id=None,
                    title="Récréation",
                    category="recess",
                    blocks_courses=True,
                    day=day,
                    start_time=start,
                    end_time=time(start.hour, 15),
                )
            )
        await db.commit()

    # A fresh session reads the day back from the database, as production does.
    async with session_factory() as db:
        events = await schedule_event_service.list_events(db, academic_year_id=YEAR)

    assert [(DayOfWeek(event.day).value, event.start_time.hour) for event in events] == [
        ("monday", 10),
        ("monday", 15),
        ("wednesday", 10),
        ("friday", 10),
        ("saturday", 10),
    ]


@pytest.mark.parametrize("subjects", [1, 7, 12, 30])
def test_no_subject_shares_the_colour_of_a_break(subjects: int) -> None:
    cache: dict[str, tuple[str, str, str]] = {}
    pause = _resolve_color("school-break", cache, "Récréation")
    activity = _resolve_color("school-activity", cache, "Étude")
    colours = {_resolve_color(None, cache, f"Matière {i}") for i in range(subjects)}
    colours |= {_resolve_color(token, cache, token) for token in _FALLBACK_CYCLE}

    assert pause not in colours and activity not in colours


# --- Ce que le statut de la tâche renvoie à l'écran ---


class _FakeAsyncResult:
    state = "SUCCESS"
    result: object = None

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        pass


def _status(monkeypatch: pytest.MonkeyPatch, state: str, result: object) -> Any:
    fake = type("Fake", (_FakeAsyncResult,), {"state": state, "result": result})
    monkeypatch.setattr("celery.result.AsyncResult", fake)
    return timetable_service.get_task_status("task")


def test_a_refusal_reaches_the_administrator(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(**_kwargs: object) -> None:
        raise TimetableGenerationError("Aucun emploi du temps possible.")

    monkeypatch.setattr(timetable_tasks, "_generate_async", refuse)
    outcome = timetable_tasks.generate_timetable_task.run(
        "local", CLASS_ID, YEAR, [], ["monday"], 8, 17, 60, None
    )

    status = _status(monkeypatch, "SUCCESS", outcome)
    assert status.status == "failed"
    assert status.message == "Aucun emploi du temps possible."


def test_a_technical_failure_never_exposes_the_raw_error(monkeypatch: pytest.MonkeyPatch) -> None:
    status = _status(monkeypatch, "FAILURE", RuntimeError("mysql://root:secret@db refused"))
    assert status.status == "failed"
    assert "secret" not in status.message
    assert "planning précédent est conservé" in status.message


def test_the_leftover_warning_comes_with_a_successful_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    status = _status(monkeypatch, "SUCCESS", {"slots": [], "warning": "Anglais (5 min)"})
    assert status.status == "completed"
    assert status.message == "Anglais (5 min)"


def _span(slot: dict[str, Any]) -> int:
    start_h, start_m = map(int, slot["start_time"].split(":"))
    end_h, end_m = map(int, slot["end_time"].split(":"))
    return (end_h * 60 + end_m) - (start_h * 60 + start_m)


@pytest.mark.asyncio
async def test_a_manual_lesson_of_a_previous_year_is_neither_listed_nor_counted(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    previous = _slot(time(8, 0), time(9, 0))
    previous.academic_year_id = YEAR - 1
    async with session_factory() as db:
        db.add(previous)
        await db.commit()

    result = await _generate(hours=2)

    assert {slot["academic_year_id"] for slot in result["slots"]} == {YEAR}
    assert sum(_span(slot) for slot in result["slots"]) == 120


@pytest.mark.asyncio
async def test_a_busy_room_is_never_given_to_this_class(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    room_id, other_class = 5, 11
    async with session_factory() as db:
        db.add_all(
            [
                Room(id=room_id, name="Labo", room_type="laboratory"),
                Class(id=other_class, name="5eme B", level_id=1, series_id=None),
            ]
        )
        await db.commit()
        db.add(
            TimetableSlot(
                class_id=other_class,
                teacher_id=99,
                subject_id=ENGLISH,
                academic_year_id=YEAR,
                day=DayOfWeek.MONDAY,
                start_time=time(8, 0),
                end_time=time(10, 0),
                room_id=room_id,
                timetable_id=None,
            )
        )
        await db.commit()

    result = await _generate(hours=1, room_id=room_id)

    generated = [slot for slot in result["slots"] if slot["class_id"] == CLASS_ID]
    assert generated
    assert all(slot["start_time"] >= "10:00" for slot in generated)
    assert all(slot["room"] == "Labo" for slot in generated)
