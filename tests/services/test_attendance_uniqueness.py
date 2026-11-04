"""Un pointage par créneau et par jour, un appel par classe et par jour.

Vraie session asynchrone sur SQLite en mémoire : les services tournent avec
leurs vraies requêtes, et la base porte les contraintes que déclarent les
modèles. C'est elle qui refuse le second envoi, y compris entre deux requêtes
simultanées : les services ne vérifient plus rien avant d'insérer.

Le 409 et son message ne se voient que sur MySQL, où l'erreur porte le nom de
la contrainte : c'est `tests/test_attendance_uniqueness_mysql.py`, qui vérifie
aussi que la migration 0091 a posé ces contraintes sous ces noms.
"""

from collections.abc import AsyncIterator
from datetime import date, time
from importlib import util as import_util
from pathlib import Path
from types import ModuleType

import pytest
import pytest_asyncio
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from pydantic import ValidationError
from sqlalchemy import Column, Integer, MetaData, Table, create_engine, func, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.academic import AcademicYear
from app.models.attendance import AttendanceContext, TeacherSessionAttendance
from app.models.timetable import TimetableSlot
from app.models.user import Student, TeacherProfile, User
from app.schemas.attendance import AttendanceRecordInput, SessionCreate
from app.schemas.teacher_attendance import TeacherAttendanceCreate, TeacherSelfDeclareCreate
from app.services import attendance_service, teacher_attendance_service

TABLES = (
    "users",
    "teacher_profiles",
    "students",
    "academic_years",
    "timetable_slots",
    "subjects",
    "classes",
    "audit_logs",
    "attendance_contexts",
    "attendance_records",
    "teacher_session_attendance",
)
JOUR = date(2026, 11, 2)
AY, CLASSE, PROF, CRENEAU, ADMIN_USER, PROF_USER = 1, 3, 1, 1, 1, 2


def _miroir() -> MetaData:
    """Les tables réelles nécessaires, et une table minimale pour chaque référence."""
    miroir = MetaData()
    for nom in TABLES:
        Base.metadata.tables[nom].to_metadata(miroir)
    for table in list(miroir.tables.values()):
        for fk in table.foreign_keys:
            cible = fk.target_fullname.split(".")[0]
            if cible not in miroir.tables:
                Table(cible, miroir, Column("id", Integer, primary_key=True))
        # SQLite n'autoincrémente que les INTEGER : on aligne les clés de test.
        if "id" in table.c:
            table.c.id.type = Integer()
    return miroir


@pytest_asyncio.fixture
async def db() -> AsyncIterator[AsyncSession]:
    moteur = create_async_engine(
        "sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    async with moteur.begin() as conn:
        await conn.run_sync(lambda c: _miroir().create_all(c))
    async with AsyncSession(moteur, expire_on_commit=False) as session:
        session.add_all(
            [
                User(id=ADMIN_USER, email="admin@ecole.ci", hashed_password="x", role="admin"),
                User(id=PROF_USER, email="prof@ecole.ci", hashed_password="x", role="teacher"),
                TeacherProfile(id=PROF, user_id=PROF_USER, first_name="Awa", last_name="Diallo"),
                AcademicYear(
                    id=AY,
                    name="2026-2027",
                    start_date=date(2026, 9, 1),
                    end_date=date(2027, 7, 31),
                    is_current=True,
                ),
                Student(
                    id=10,
                    first_name="Aminata",
                    last_name="Traoré",
                    first_name_key="aminata",
                    last_name_key="traore",
                ),
            ]
        )
        await session.flush()
        session.add(
            TimetableSlot(
                id=CRENEAU,
                class_id=CLASSE,
                teacher_id=PROF,
                subject_id=1,
                academic_year_id=AY,
                day="monday",
                start_time=time(8, 0),
                end_time=time(9, 0),
            )
        )
        await session.commit()
        yield session
    await moteur.dispose()


def _appel(statut: str = "present") -> SessionCreate:
    return SessionCreate(
        entity_type="class",
        context_id=CLASSE,
        date=JOUR,
        academic_year_id=AY,
        records=[AttendanceRecordInput(student_id=10, status=statut)],
    )


async def _nombre(db: AsyncSession, modele: type) -> int:
    return int((await db.execute(select(func.count()).select_from(modele))).scalar_one())


# ---------------------------------------------------------------------------
# Appel du jour
# ---------------------------------------------------------------------------


async def test_un_second_appel_le_meme_jour_est_refuse(db: AsyncSession) -> None:
    await attendance_service.create_session(db, _appel(), created_by=ADMIN_USER)

    with pytest.raises(IntegrityError):
        await attendance_service.create_session(db, _appel("absent"), created_by=ADMIN_USER)
    await db.rollback()

    assert await _nombre(db, AttendanceContext) == 1


async def test_le_lendemain_un_nouvel_appel_est_accepte(db: AsyncSession) -> None:
    await attendance_service.create_session(db, _appel(), created_by=ADMIN_USER)
    demain = _appel().model_copy(update={"date": date(2026, 11, 3)})

    await attendance_service.create_session(db, demain, created_by=ADMIN_USER)

    assert await _nombre(db, AttendanceContext) == 2


def test_un_eleve_en_double_dans_l_appel_est_refuse_avant_toute_ecriture() -> None:
    with pytest.raises(ValidationError, match="deux fois"):
        SessionCreate(
            entity_type="class",
            context_id=CLASSE,
            date=JOUR,
            academic_year_id=AY,
            records=[
                AttendanceRecordInput(student_id=10, status="present"),
                AttendanceRecordInput(student_id=10, status="absent"),
            ],
        )


# ---------------------------------------------------------------------------
# Pointage enseignant
# ---------------------------------------------------------------------------


async def test_un_second_pointage_du_meme_creneau_est_refuse(db: AsyncSession) -> None:
    saisie = TeacherAttendanceCreate(slot_id=CRENEAU, date=JOUR, status="present")
    await teacher_attendance_service.record_attendance(
        db, PROF, saisie, declared_by_user_id=ADMIN_USER
    )

    with pytest.raises(IntegrityError):
        await teacher_attendance_service.record_attendance(
            db, PROF, saisie, declared_by_user_id=ADMIN_USER
        )
    await db.rollback()

    assert await _nombre(db, TeacherSessionAttendance) == 1


async def test_le_prof_ne_peut_pas_se_declarer_deux_fois(db: AsyncSession) -> None:
    saisie = TeacherSelfDeclareCreate(slot_id=CRENEAU, date=JOUR, status="present")
    await teacher_attendance_service.self_declare(db, PROF_USER, saisie)

    with pytest.raises(IntegrityError):
        await teacher_attendance_service.self_declare(db, PROF_USER, saisie)
    await db.rollback()

    assert await _nombre(db, TeacherSessionAttendance) == 1


async def test_plusieurs_absences_hors_emploi_du_temps_restent_possibles(db: AsyncSession) -> None:
    """Réunion le matin, formation l'après-midi : deux lignes sans créneau."""
    absence = TeacherAttendanceCreate(slot_id=None, date=JOUR, status="absent_excused")
    await teacher_attendance_service.record_attendance(
        db, PROF, absence, declared_by_user_id=ADMIN_USER
    )
    await teacher_attendance_service.record_attendance(
        db, PROF, absence, declared_by_user_id=ADMIN_USER
    )

    assert await _nombre(db, TeacherSessionAttendance) == 2


# ---------------------------------------------------------------------------
# Garde de la migration
# ---------------------------------------------------------------------------


def _migration() -> ModuleType:
    path = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "20261104_0091_attendance_uniqueness.py"
    )
    spec = import_util.spec_from_file_location("migration_0091", path)
    assert spec is not None and spec.loader is not None
    module = import_util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_la_migration_compte_les_doublons_et_ignore_les_creneaux_vides() -> None:
    migration = _migration()
    moteur = create_engine("sqlite://")
    with moteur.begin() as conn:
        conn.execute(text("CREATE TABLE t (teacher_id INT, slot_id INT, date TEXT)"))
        conn.execute(
            text(
                "INSERT INTO t VALUES (1, 5, '2026-11-02'), (1, 5, '2026-11-02'), "
                "(1, NULL, '2026-11-02'), (1, NULL, '2026-11-02'), (2, 5, '2026-11-02')"
            )
        )
        groupes = migration.duplicate_groups(conn, "t", ("teacher_id", "slot_id", "date"))

    assert groupes == 1


def test_la_migration_s_arrete_sur_un_doublon_sans_rien_modifier() -> None:
    """Choisir la ligne à garder est une décision métier : la migration nomme
    la table en cause et ne pose aucune contrainte, pas même sur les autres."""
    migration = _migration()
    moteur = create_engine("sqlite://")
    with moteur.begin() as conn:
        conn.execute(
            text("CREATE TABLE teacher_session_attendance (teacher_id INT, slot_id INT, date TEXT)")
        )
        conn.execute(
            text("CREATE TABLE attendance_contexts (entity_type TEXT, context_id INT, date TEXT)")
        )
        conn.execute(text("CREATE TABLE attendance_records (context_id INT, student_id INT)"))
        conn.execute(text("INSERT INTO attendance_records VALUES (1, 10), (1, 10)"))

        with Operations.context(MigrationContext.configure(conn)):
            with pytest.raises(RuntimeError, match="attendance_records"):
                migration.upgrade()

        posees = [
            u["name"]
            for table in ("teacher_session_attendance", "attendance_contexts", "attendance_records")
            for u in inspect(conn).get_unique_constraints(table)
        ]
    assert posees == []
