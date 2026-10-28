"""Emploi du temps et enseignant retenu par classe.

Diagnostic, génération automatique, saisie manuelle et bulletins suivent
l'enseignant résolu pour la classe, pas l'enseignant unique de la matière.
Vraie base SQLite asynchrone ; la génération OR-Tools est remplacée par un
faux `delay` qui enregistre ses arguments.
"""

from collections.abc import AsyncIterator
from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import Integer, MetaData
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.core.exceptions import BusinessValidationError, ConflictError
from app.models.academic import AcademicYear, Class, Level, Subject
from app.models.timetable import DayOfWeek
from app.models.user import TeacherProfile
from app.schemas.class_subject_teachers import ClassSubjectTeacherAssignment
from app.schemas.timetable import TimetableSlotCreate, TimetableSlotUpdate
from app.services import class_subject_teacher_service as cst
from app.services import subject_teachers as subject_svc
from app.services import timetable_service as svc
from app.services.reports_subject_stats import enrich_subject_rows

ANNEE_ID = 1
NIVEAU_6E = 1
NIVEAU_5E = 2
CLASSE_6A = 10
CLASSE_6B = 11
CLASSE_5A = 12
KOUASSI, TRAORE, YAO = 1, 2, 3
ACTEUR = 1
TABLES = (
    "academic_years",
    "school_settings",
    "levels",
    "classes",
    "rooms",
    "subjects",
    "teacher_profiles",
    "subject_teachers",
    "class_subject_teachers",
    "timetable_slots",
    "teacher_availabilities",
    "audit_logs",
)


def _schema() -> list[Any]:
    miroir = MetaData()
    for table in Base.metadata.tables.values():
        table.to_metadata(miroir)
    tables = []
    for nom in TABLES:
        table = miroir.tables[nom]
        table.c.id.type = Integer()
        tables.append(table)
    return tables


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    moteur = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with moteur.begin() as conn:
        await conn.run_sync(lambda c: MetaData().create_all(c, tables=_schema()))

    async with AsyncSession(moteur, expire_on_commit=False) as db:
        db.add_all(
            [
                AcademicYear(
                    id=ANNEE_ID,
                    name="2026-2027",
                    start_date=date(2026, 9, 1),
                    end_date=date(2027, 7, 1),
                    is_current=True,
                ),
                Level(id=NIVEAU_6E, name="6e", order=1),
                Class(id=CLASSE_6A, name="6eme A", level_id=NIVEAU_6E),
                Class(id=CLASSE_6B, name="6eme B", level_id=NIVEAU_6E),
                TeacherProfile(id=KOUASSI, user_id=101, first_name="Jean", last_name="Kouassi"),
                TeacherProfile(id=TRAORE, user_id=102, first_name="Awa", last_name="Traoré"),
                TeacherProfile(id=YAO, user_id=103, first_name="Sophie", last_name="Yao"),
            ]
        )
        await db.commit()
        yield db
    await moteur.dispose()


async def _matiere(db: AsyncSession, nom: str, enseignants: list[int], heures: int) -> Subject:
    matiere = Subject(name=nom, level_id=NIVEAU_6E, hours_per_week=heures)
    db.add(matiere)
    await db.flush()
    await subject_svc.set_subject_teachers(db, matiere, enseignants)
    await db.commit()
    return matiere


async def _choisir(db: AsyncSession, classe: int, matiere: int, enseignant: int) -> None:
    await cst.save_class_teachers(
        db,
        classe,
        [ClassSubjectTeacherAssignment(subject_id=matiere, teacher_id=enseignant)],
        actor=ACTEUR,
    )


def _creneau(
    classe: int, matiere: int, enseignant: int, debut: str, fin: str
) -> TimetableSlotCreate:
    return TimetableSlotCreate(
        class_id=classe,
        teacher_id=enseignant,
        subject_id=matiere,
        academic_year_id=ANNEE_ID,
        day=DayOfWeek.MONDAY,
        start_time=debut,
        end_time=fin,
    )


@pytest.mark.asyncio
async def test_diagnostic_prend_l_enseignant_de_la_classe(session: AsyncSession) -> None:
    maths = await _matiere(session, "Mathématiques", [KOUASSI, TRAORE], heures=4)
    anglais = await _matiere(session, "Anglais", [KOUASSI, YAO], heures=3)
    await _choisir(session, CLASSE_6A, maths.id, KOUASSI)
    await _choisir(session, CLASSE_6B, maths.id, TRAORE)

    diag_a = await svc.diagnostic_for_class(session, CLASSE_6A)
    diag_b = await svc.diagnostic_for_class(session, CLASSE_6B)

    assert {
        (m["name"], m["teacher_id"], m["teacher_name"]) for m in diag_a["subjects_with_teacher"]
    } == {("Mathématiques", KOUASSI, "Jean Kouassi")}
    assert [m["name"] for m in diag_a["subjects_without_teacher"]] == [anglais.name]
    assert {(m["name"], m["teacher_id"]) for m in diag_b["subjects_with_teacher"]} == {
        ("Mathématiques", TRAORE)
    }
    assert diag_a["ready"] is False


@pytest.mark.asyncio
async def test_generation_bloquee_si_une_matiere_n_a_pas_d_enseignant_dans_la_classe(
    session: AsyncSession,
) -> None:
    await _matiere(session, "Anglais", [KOUASSI, YAO], heures=3)

    with pytest.raises(BusinessValidationError) as erreur:
        await svc.auto_generate(session, "tenant-test", CLASSE_6A)

    assert "Anglais" in erreur.value.detail
    assert "Enseignants de la classe" in erreur.value.detail


@pytest.mark.asyncio
async def test_generation_envoie_l_enseignant_resolu_pour_chaque_matiere(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    appels: list[tuple[Any, ...]] = []

    class _FauxTache:
        id = "tache-1"

    def _delay(*args: Any) -> _FauxTache:
        appels.append(args)
        return _FauxTache()

    import app.tasks.timetable_tasks as taches

    monkeypatch.setattr(taches, "generate_timetable_task", SimpleNamespace(delay=_delay))
    maths = await _matiere(session, "Mathématiques", [KOUASSI, TRAORE], heures=4)
    anglais = await _matiere(session, "Anglais", [YAO], heures=3)
    await _choisir(session, CLASSE_6B, maths.id, TRAORE)

    await svc.auto_generate(session, "tenant-test", CLASSE_6B)

    assert len(appels) == 1
    assignments = appels[0][3]
    assert sorted(
        (a["subject_id"], a["teacher_id"], a["hours_per_week"]) for a in assignments
    ) == sorted([(maths.id, TRAORE, 4), (anglais.id, YAO, 3)])


@pytest.mark.asyncio
async def test_creneau_refuse_pour_un_enseignant_qui_n_enseigne_pas_la_matiere(
    session: AsyncSession,
) -> None:
    anglais = await _matiere(session, "Anglais", [YAO], heures=3)

    with pytest.raises(BusinessValidationError) as erreur:
        await svc.create_slot(
            session, _creneau(CLASSE_6A, anglais.id, KOUASSI, "08:00", "09:00"), created_by=ACTEUR
        )

    assert "Jean Kouassi" in erreur.value.detail
    assert "n'enseigne pas « Anglais » dans ce niveau" in erreur.value.detail


@pytest.mark.asyncio
async def test_creneau_refuse_si_la_classe_a_choisi_un_autre_enseignant(
    session: AsyncSession,
) -> None:
    maths = await _matiere(session, "Mathématiques", [KOUASSI, TRAORE], heures=4)
    await _choisir(session, CLASSE_6A, maths.id, TRAORE)

    with pytest.raises(BusinessValidationError) as erreur:
        await svc.create_slot(
            session, _creneau(CLASSE_6A, maths.id, KOUASSI, "08:00", "09:00"), created_by=ACTEUR
        )
    assert "est confiée à" in erreur.value.detail

    cree = await svc.create_slot(
        session, _creneau(CLASSE_6A, maths.id, TRAORE, "08:00", "09:00"), created_by=ACTEUR
    )
    assert cree.teacher_id == TRAORE


@pytest.mark.asyncio
async def test_creneau_accepte_pour_un_enseignant_retenu(session: AsyncSession) -> None:
    anglais = await _matiere(session, "Anglais", [YAO], heures=3)

    cree = await svc.create_slot(
        session, _creneau(CLASSE_6A, anglais.id, YAO, "08:00", "09:00"), created_by=ACTEUR
    )

    assert (cree.teacher_id, cree.subject_name) == (YAO, "Anglais")


@pytest.mark.asyncio
async def test_modification_refusee_si_la_matiere_change_pour_une_non_enseignee(
    session: AsyncSession,
) -> None:
    maths = await _matiere(session, "Mathématiques", [KOUASSI, TRAORE], heures=4)
    anglais = await _matiere(session, "Anglais", [YAO], heures=3)
    cree = await svc.create_slot(
        session, _creneau(CLASSE_6A, maths.id, KOUASSI, "08:00", "09:00"), created_by=ACTEUR
    )

    with pytest.raises(BusinessValidationError):
        await svc.update_slot(
            session,
            cree.id,
            TimetableSlotUpdate(subject_id=anglais.id),
            updated_by=ACTEUR,
        )


@pytest.mark.asyncio
async def test_conflit_entre_deux_classes_reste_refuse(session: AsyncSession) -> None:
    maths = await _matiere(session, "Mathématiques", [KOUASSI, TRAORE], heures=4)
    await svc.create_slot(
        session, _creneau(CLASSE_6A, maths.id, KOUASSI, "08:00", "09:00"), created_by=ACTEUR
    )

    with pytest.raises(ConflictError):
        await svc.create_slot(
            session, _creneau(CLASSE_6B, maths.id, KOUASSI, "08:00", "09:00"), created_by=ACTEUR
        )


@pytest.mark.asyncio
async def test_modification_horaire_passe_meme_si_l_enseignant_n_est_plus_retenu(
    session: AsyncSession,
) -> None:
    maths = await _matiere(session, "Mathématiques", [KOUASSI, TRAORE], heures=4)
    cree = await svc.create_slot(
        session, _creneau(CLASSE_6A, maths.id, KOUASSI, "08:00", "09:00"), created_by=ACTEUR
    )
    await subject_svc.set_subject_teachers(session, maths, [TRAORE])
    await session.commit()

    modifie = await svc.update_slot(
        session,
        cree.id,
        TimetableSlotUpdate(start_time="10:00", end_time="11:00"),
        updated_by=ACTEUR,
    )

    assert modifie.start_time == "10:00"


@pytest.mark.asyncio
async def test_changer_l_enseignant_vers_un_non_retenu_est_refuse(session: AsyncSession) -> None:
    maths = await _matiere(session, "Mathématiques", [KOUASSI, TRAORE], heures=4)
    cree = await svc.create_slot(
        session, _creneau(CLASSE_6A, maths.id, KOUASSI, "08:00", "09:00"), created_by=ACTEUR
    )

    with pytest.raises(BusinessValidationError) as erreur:
        await svc.update_slot(
            session,
            cree.id,
            TimetableSlotUpdate(teacher_id=YAO),
            updated_by=ACTEUR,
        )

    assert "Sophie Yao" in erreur.value.detail


@pytest.mark.asyncio
async def test_diagnostic_d_une_classe_sans_matiere_pour_son_niveau(
    session: AsyncSession,
) -> None:
    session.add(Level(id=NIVEAU_5E, name="5e", order=2))
    session.add(Class(id=CLASSE_5A, name="5eme A", level_id=NIVEAU_5E))
    await session.commit()

    diagnostic = await svc.diagnostic_for_class(session, CLASSE_5A)

    assert diagnostic["ready"] is False
    assert diagnostic["subjects_without_teacher"] == []


def test_bulletin_affiche_le_prof_de_la_classe_du_bulletin() -> None:
    """Deux classes du même niveau, deux enseignants : chaque bulletin nomme le sien."""
    matiere = SimpleNamespace(name="Mathématiques", teacher=None)

    def _bulletin(student_id: int) -> SimpleNamespace:
        return SimpleNamespace(
            student_id=student_id,
            subject_averages=[
                SimpleNamespace(subject_id=7, average=12, coefficient=4, subject=matiere)
            ],
        )

    noms_6a = {7: "Jean Kouassi"}
    noms_6b = {7: "Awa Traoré"}

    ligne_6a = enrich_subject_rows(_bulletin(1), {}, noms_6a)[0]
    ligne_6b = enrich_subject_rows(_bulletin(2), {}, noms_6b)[0]

    assert ligne_6a["teacher_name"] == "Jean Kouassi"
    assert ligne_6b["teacher_name"] == "Awa Traoré"
