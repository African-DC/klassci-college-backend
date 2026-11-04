"""Un pointage garde son cours quand l'emploi du temps change.

Régénérer l'emploi du temps supprime les créneaux générés de la classe. Le
pointage enseignant pointait vers l'un d'eux, et la clé étrangère le remettait
à NULL : sur la démo, les 800 pointages d'une base régénérée ne disaient plus
de quel cours il s'agissait.

Ces tests saisissent un pointage par le vrai service, puis lancent la vraie
génération (solveur compris) ou la vraie modification de créneau, sur une base
SQLite qui applique ses clés étrangères comme MySQL. Ils relisent ensuite le
pointage tel que l'administration le reçoit.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date, time
from importlib import util as import_util
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy import Column, Integer, MetaData, Table, create_engine, event, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.academic import AcademicYear, Class, Subject
from app.models.attendance import TeacherSessionAttendance
from app.models.timetable import DayOfWeek, Timetable, TimetableSlot
from app.models.user import TeacherProfile, User
from app.schemas.teacher_attendance import TeacherAttendanceCreate, TeacherSelfDeclareCreate
from app.schemas.timetable import TimetableSlotUpdate
from app.services import teacher_attendance_service, timetable_service
from app.tasks import timetable_tasks
from app.tasks.timetable_tasks import _generate_async

AY = 2026
CLASS_ID = 10
TEACHER = 1
ENGLISH = 20
ADMIN_USER, TEACHER_USER = 100, 101
PAST_MONDAY = date(2026, 11, 2)
GENERATED_SLOT = 7

TABLES = (
    "users",
    "academic_years",
    "classes",
    "subjects",
    "rooms",
    "teacher_profiles",
    "timetables",
    "timetable_slots",
    "schedule_events",
    "teacher_availabilities",
    "audit_logs",
    "teacher_session_attendance",
)


def _mirror() -> MetaData:
    """Les tables réelles nécessaires, et une table minimale pour chaque référence."""
    mirror = MetaData()
    for name in TABLES:
        Base.metadata.tables[name].to_metadata(mirror)
    for table in list(mirror.tables.values()):
        for fk in table.foreign_keys:
            target = fk.target_fullname.split(".")[0]
            if target not in mirror.tables:
                Table(target, mirror, Column("id", Integer, primary_key=True))
        # SQLite n'autoincrémente que les INTEGER : on aligne les clés de test.
        table.c.id.type = Integer()
    return mirror


@pytest.fixture
async def session_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)

    # Comme MySQL : supprimer un créneau remet `slot_id` à NULL. Sans cette
    # ligne, SQLite ignorerait la clé étrangère et le test ne prouverait rien.
    @event.listens_for(engine.sync_engine, "connect")
    def _foreign_keys(dbapi_connection, _record):  # type: ignore[no-untyped-def]
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    mirror = _mirror()
    async with engine.begin() as conn:
        await conn.run_sync(lambda sync: mirror.create_all(sync))

    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as db:
        await db.execute(text("INSERT INTO levels (id) VALUES (1)"))
        db.add_all(
            [
                User(id=ADMIN_USER, email="admin@ecole.ci", hashed_password="x", role="admin"),
                User(id=TEACHER_USER, email="prof@ecole.ci", hashed_password="x", role="teacher"),
                AcademicYear(
                    id=AY,
                    name="2026-2027",
                    start_date=date(2026, 9, 1),
                    end_date=date(2027, 7, 31),
                    is_current=True,
                ),
                Class(id=CLASS_ID, name="6ème A", level_id=1, series_id=None),
                Subject(id=ENGLISH, name="Anglais", coefficient=2),
                TeacherProfile(
                    id=TEACHER, user_id=TEACHER_USER, first_name="Yves", last_name="Koné"
                ),
            ]
        )
        await db.flush()
        db.add(Timetable(id=1, class_id=CLASS_ID, academic_year_id=AY))
        await db.flush()
        db.add(
            TimetableSlot(
                id=GENERATED_SLOT,
                timetable_id=1,
                class_id=CLASS_ID,
                teacher_id=TEACHER,
                subject_id=ENGLISH,
                academic_year_id=AY,
                day=DayOfWeek.MONDAY,
                start_time=time(8, 0),
                end_time=time(9, 0),
            )
        )
        await db.commit()

    @asynccontextmanager
    async def _session(_tenant: str) -> AsyncIterator[AsyncSession]:
        async with factory() as db:
            yield db

    monkeypatch.setattr(timetable_tasks, "_tenant_timetable_session", _session)
    yield factory
    await engine.dispose()


async def _record(factory: async_sessionmaker[AsyncSession]) -> int:
    async with factory() as db:
        saisie = TeacherAttendanceCreate(slot_id=GENERATED_SLOT, date=PAST_MONDAY, status="present")
        response = await teacher_attendance_service.record_attendance(
            db, TEACHER, saisie, declared_by_user_id=ADMIN_USER
        )
    return response.id


async def _read(factory: async_sessionmaker[AsyncSession], attendance_id: int):  # type: ignore[no-untyped-def]
    async with factory() as db:
        listing = await teacher_attendance_service.list_for_teacher(db, TEACHER)
    return next(item for item in listing.items if item.id == attendance_id)


async def _regenerate() -> None:
    await _generate_async(
        tenant_id="local",
        class_id=CLASS_ID,
        academic_year_id=AY,
        assignments_data=[{"teacher_id": TEACHER, "subject_id": ENGLISH, "hours_per_week": 1}],
        day_names=["tuesday"],
        day_start_hour=10,
        day_end_hour=12,
        slot_duration_minutes=60,
        room_id=None,
    )


@pytest.mark.asyncio
async def test_a_regenerated_timetable_keeps_the_course_of_past_sign_ins(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    attendance_id = await _record(session_factory)

    await _regenerate()

    async with session_factory() as db:
        slots = list((await db.execute(select(TimetableSlot))).scalars().all())
        stored = await db.get(TeacherSessionAttendance, attendance_id)
    # Le créneau pointé a bien disparu : le nouveau plan est le mardi.
    assert GENERATED_SLOT not in {s.id for s in slots}
    assert stored is not None
    assert (stored.class_id, stored.subject_id) == (CLASS_ID, ENGLISH)
    assert (stored.planned_start, stored.planned_end) == (time(8, 0), time(9, 0))

    item = await _read(session_factory, attendance_id)
    assert item.slot_summary == "Lundi 08:00-09:00 Anglais 6ème A"


@pytest.mark.asyncio
async def test_moving_a_slot_does_not_rewrite_a_past_sign_in(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    attendance_id = await _record(session_factory)

    async with session_factory() as db:
        await timetable_service.update_slot(
            db,
            GENERATED_SLOT,
            TimetableSlotUpdate(start_time="14:00", end_time="15:00"),
            updated_by=ADMIN_USER,
        )

    item = await _read(session_factory, attendance_id)
    assert item.slot_id == GENERATED_SLOT
    assert item.slot_summary == "Lundi 08:00-09:00 Anglais 6ème A"


@pytest.mark.asyncio
async def test_a_self_declaration_also_keeps_its_course(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as db:
        saisie = TeacherSelfDeclareCreate(slot_id=GENERATED_SLOT, date=PAST_MONDAY, status="late")
        response = await teacher_attendance_service.self_declare(db, TEACHER_USER, saisie)

    await _regenerate()

    item = await _read(session_factory, response.id)
    assert item.slot_summary == "Lundi 08:00-09:00 Anglais 6ème A"


@pytest.mark.asyncio
async def test_an_absence_outside_the_timetable_has_no_course(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as db:
        absence = TeacherAttendanceCreate(slot_id=None, date=PAST_MONDAY, status="absent_excused")
        response = await teacher_attendance_service.record_attendance(
            db, TEACHER, absence, declared_by_user_id=ADMIN_USER
        )

    item = await _read(session_factory, response.id)
    assert item.slot_id is None
    assert item.slot_summary is None


# ---------------------------------------------------------------------------
# Reprise des pointages existants (migration 0092)
# ---------------------------------------------------------------------------


def _migration() -> ModuleType:
    path = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "20261104_0092_attendance_course_snapshot.py"
    )
    spec = import_util.spec_from_file_location("migration_0092", path)
    assert spec is not None and spec.loader is not None
    module = import_util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_migration_copies_the_course_of_linked_sign_ins_only() -> None:
    migration = _migration()
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE timetable_slots (id INT, class_id INT, subject_id INT, "
                "start_time TEXT, end_time TEXT)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE teacher_session_attendance (id INT, slot_id INT, class_id INT, "
                "subject_id INT, planned_start TEXT, planned_end TEXT)"
            )
        )
        conn.execute(text("INSERT INTO timetable_slots VALUES (5, 10, 20, '08:00', '09:00')"))
        conn.execute(
            text(
                "INSERT INTO teacher_session_attendance VALUES "
                "(1, 5, NULL, NULL, NULL, NULL), "  # lié : recopié
                "(2, NULL, NULL, NULL, NULL, NULL), "  # hors emploi du temps
                "(3, 5, 11, 21, '10:00', '11:00')"  # déjà renseigné : intact
            )
        )

        copied = migration.copy_course_from_slot(conn)
        rows = conn.execute(
            text(
                "SELECT id, class_id, subject_id, planned_start, planned_end "
                "FROM teacher_session_attendance ORDER BY id"
            )
        ).all()

    assert copied == 1
    assert [tuple(r) for r in rows] == [
        (1, 10, 20, "08:00", "09:00"),
        (2, None, None, None, None),
        (3, 11, 21, "10:00", "11:00"),
    ]
