"""Portée d'enseignement : affectations, créneaux de l'année, remplacements.

Vraie session asynchrone sur SQLite en mémoire : le calcul lit les mêmes tables
que la production, et le portail enseignant refuse ou accepte par ce calcul.
"""

from collections.abc import AsyncIterator
from datetime import date, time, timedelta
from typing import Any

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import Integer, MetaData
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.academic import AcademicYear, Class, Level, Subject
from app.models.class_subject_teacher import ClassSubjectTeacher
from app.models.leave import LeaveRequest, LeaveStatus
from app.models.subject_teacher import SubjectTeacher
from app.models.timetable import TimetableSlot
from app.models.user import TeacherProfile
from app.services import teacher_portal_service
from app.services.teaching_scope import teaching_scope

NIVEAU_6E, NIVEAU_5E = 1, 2
CLASSE_6A, CLASSE_6B, CLASSE_5A = 10, 11, 12
MATHS_6E, FRANCAIS_6E, SVT_5E = 20, 21, 22
KOUASSI, TRAORE, YAO = 1, 2, 3
USER = {KOUASSI: 101, TRAORE: 102, YAO: 103}
ANNEE, ANNEE_PASSEE = 1, 2
LUNDI = date(2026, 11, 2)
TABLES = (
    "levels",
    "series",
    "classes",
    "subjects",
    "teacher_profiles",
    "subject_teachers",
    "class_subject_teachers",
    "academic_years",
    "timetable_slots",
    "leave_requests",
    "students",
    "enrollments",
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


def _creneau(enseignant: int, classe: int, matiere: int, annee: int) -> TimetableSlot:
    return TimetableSlot(
        teacher_id=enseignant,
        class_id=classe,
        subject_id=matiere,
        academic_year_id=annee,
        day="monday",
        start_time=time(8, 0),
        end_time=time(9, 0),
    )


@pytest_asyncio.fixture
async def db() -> AsyncIterator[AsyncSession]:
    """Maths 6e : Kouassi seul retenu. Français 6e : Traoré et Yao, Traoré choisi
    en 6e A. Yao a un créneau en 5e A cette année, et en 6e B l'an dernier."""
    moteur = create_async_engine(
        "sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    async with moteur.begin() as conn:
        await conn.run_sync(lambda c: MetaData().create_all(c, tables=_schema()))

    async with AsyncSession(moteur, expire_on_commit=False) as session:
        session.add_all(
            [
                Level(id=NIVEAU_6E, name="6e", order=1),
                Level(id=NIVEAU_5E, name="5e", order=2),
                Class(id=CLASSE_6A, name="6eme A", level_id=NIVEAU_6E),
                Class(id=CLASSE_6B, name="6eme B", level_id=NIVEAU_6E),
                Class(id=CLASSE_5A, name="5eme A", level_id=NIVEAU_5E),
                AcademicYear(
                    id=ANNEE,
                    name="2026-2027",
                    start_date=date(2026, 9, 1),
                    end_date=date(2027, 7, 31),
                    is_current=True,
                ),
                AcademicYear(
                    id=ANNEE_PASSEE,
                    name="2025-2026",
                    start_date=date(2025, 9, 1),
                    end_date=date(2026, 7, 31),
                    is_current=False,
                ),
                Subject(id=MATHS_6E, name="Maths", level_id=NIVEAU_6E, hours_per_week=4),
                Subject(id=FRANCAIS_6E, name="Français", level_id=NIVEAU_6E, hours_per_week=5),
                Subject(id=SVT_5E, name="SVT", level_id=NIVEAU_5E, hours_per_week=2),
            ]
            + [
                TeacherProfile(id=t, user_id=USER[t], first_name="Prof", last_name=str(t))
                for t in (KOUASSI, TRAORE, YAO)
            ]
        )
        await session.flush()
        session.add_all(
            [
                SubjectTeacher(subject_id=MATHS_6E, teacher_id=KOUASSI, position=0),
                SubjectTeacher(subject_id=FRANCAIS_6E, teacher_id=TRAORE, position=0),
                SubjectTeacher(subject_id=FRANCAIS_6E, teacher_id=YAO, position=1),
                ClassSubjectTeacher(class_id=CLASSE_6A, subject_id=FRANCAIS_6E, teacher_id=TRAORE),
                _creneau(YAO, CLASSE_5A, SVT_5E, ANNEE),
                _creneau(YAO, CLASSE_6B, FRANCAIS_6E, ANNEE_PASSEE),
            ]
        )
        await session.commit()
        yield session
    await moteur.dispose()


def _conge(absent: int, interim: int, debut: date, fin: date, statut: LeaveStatus) -> LeaveRequest:
    return LeaveRequest(
        user_id=USER[absent],
        leave_type="sick",
        start_date=debut,
        end_date=fin,
        status=statut,
        interim_teacher_id=interim,
    )


# ---------------------------------------------------------------------------
# Les trois sources
# ---------------------------------------------------------------------------


async def test_seul_enseignant_retenu_couvre_toutes_les_classes_du_niveau(
    db: AsyncSession,
) -> None:
    """Pas de créneau, pas de choix explicite : la règle de résolution suffit."""
    portee = await teaching_scope(db, KOUASSI, on=LUNDI)
    assert portee.class_ids == {CLASSE_6A, CLASSE_6B}


async def test_le_choix_explicite_donne_la_classe_et_seulement_elle(db: AsyncSession) -> None:
    portee = await teaching_scope(db, TRAORE, on=LUNDI)
    assert portee.covers_class(CLASSE_6A)
    assert not portee.covers_class(CLASSE_6B), "deux retenus, aucun choix : personne"


async def test_un_creneau_de_l_an_dernier_ne_donne_plus_la_classe(db: AsyncSession) -> None:
    portee = await teaching_scope(db, YAO, on=LUNDI)
    assert portee.class_ids == {CLASSE_5A}


# ---------------------------------------------------------------------------
# Remplacements
# ---------------------------------------------------------------------------


async def test_le_remplacant_couvre_les_classes_de_l_absent_pendant_l_interim(
    db: AsyncSession,
) -> None:
    db.add(_conge(KOUASSI, YAO, LUNDI, LUNDI + timedelta(days=11), LeaveStatus.APPROVED))
    await db.commit()

    pendant = await teaching_scope(db, YAO, on=LUNDI + timedelta(days=3))
    apres = await teaching_scope(db, YAO, on=LUNDI + timedelta(days=12))

    assert pendant.class_ids == {CLASSE_5A, CLASSE_6A, CLASSE_6B}
    assert pendant.replaced_teacher_ids == {KOUASSI}
    assert apres.class_ids == {CLASSE_5A}


async def test_un_conge_non_approuve_ne_donne_rien(db: AsyncSession) -> None:
    db.add(_conge(KOUASSI, YAO, LUNDI, LUNDI + timedelta(days=11), LeaveStatus.PENDING))
    await db.commit()

    portee = await teaching_scope(db, YAO, on=LUNDI + timedelta(days=3))
    assert portee.class_ids == {CLASSE_5A}


# ---------------------------------------------------------------------------
# Le portail enseignant passe par ce calcul
# ---------------------------------------------------------------------------


async def test_le_portail_refuse_une_classe_hors_portee(db: AsyncSession) -> None:
    with pytest.raises(HTTPException) as refus:
        await teacher_portal_service.get_class_roster(db, USER[TRAORE], CLASSE_6B)
    assert refus.value.status_code == 403


async def test_le_portail_ouvre_la_classe_au_remplacant_pendant_l_interim(
    db: AsyncSession,
) -> None:
    aujourd_hui = date.today()
    db.add(
        _conge(
            KOUASSI,
            YAO,
            aujourd_hui - timedelta(days=1),
            aujourd_hui + timedelta(days=1),
            LeaveStatus.APPROVED,
        )
    )
    await db.commit()

    liste = await teacher_portal_service.get_class_roster(db, USER[YAO], CLASSE_6A)

    assert (liste.class_id, liste.class_name, liste.academic_year_id) == (
        CLASSE_6A,
        "6eme A",
        ANNEE,
    )


async def test_le_portail_ouvre_la_classe_choisie_sans_conge(db: AsyncSession) -> None:
    liste = await teacher_portal_service.get_class_roster(db, USER[TRAORE], CLASSE_6A)
    assert liste.class_name == "6eme A"


async def test_le_portail_refuse_la_classe_d_un_creneau_de_l_an_dernier(db: AsyncSession) -> None:
    with pytest.raises(HTTPException) as refus:
        await teacher_portal_service.get_class_roster(db, USER[YAO], CLASSE_6B)
    assert refus.value.status_code == 403


async def test_sans_annee_en_cours_aucun_creneau_n_ouvre_une_classe(db: AsyncSession) -> None:
    annee = await db.get(AcademicYear, ANNEE)
    assert annee is not None
    annee.is_current = False
    await db.commit()

    portee = await teaching_scope(db, YAO, on=LUNDI)
    assert portee.class_ids == frozenset()


async def test_la_liste_des_classes_suit_la_portee(
    db: AsyncSession,
) -> None:
    """Ce que le remplaçant peut ouvrir, il le voit aussi dans sa liste."""
    aujourd_hui = date.today()
    db.add(
        _conge(
            KOUASSI,
            YAO,
            aujourd_hui - timedelta(days=1),
            aujourd_hui + timedelta(days=1),
            LeaveStatus.APPROVED,
        )
    )
    await db.commit()

    classes = await teacher_portal_service.get_classes(db, USER[YAO])
    lignes = {(c.class_id, c.subject_name) for c in classes.items}

    assert lignes == {
        (CLASSE_5A, "SVT"),
        (CLASSE_6A, "Maths"),
        (CLASSE_6B, "Maths"),
    }
