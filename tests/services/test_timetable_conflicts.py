"""Refus de créneau — le message doit dire pourquoi, sur une vraie base.

Un refus qui ne nomme ni l'enseignant, ni l'heure, ni la classe oblige la
personne qui pose l'emploi du temps à chercher elle-même où est le cours qui
bloque. Ces tests exécutent la vraie création de créneau et lisent le message
rendu : ils échouent si on retombe sur un « conflit détecté » opaque.

Les deux empêchements sont distincts et ne se disent pas pareil : un cours
ailleurs se déplace, une indisponibilité déclarée se discute avec l'intéressé.
"""

from collections.abc import Iterator
from datetime import time

import pytest
from sqlalchemy import Integer, MetaData, Table, create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.core.exceptions import ConflictError
from app.models.academic import Class, Subject
from app.models.timetable import DayOfWeek, TeacherAvailability, TimetableSlot
from app.models.user import TeacherProfile
from app.schemas.timetable import TimetableSlotCreate
from app.services import timetable_service as svc

ANNEE = 2026
KOUASSI = 1
SIXIEME_A = 10
SIXIEME_B = 11
MATHS = 20


class _AsyncBridge:
    """Donne l'allure d'une `AsyncSession` à une session synchrone."""

    def __init__(self, session: Session) -> None:
        self._session = session

    async def execute(self, statement: object) -> object:
        return self._session.execute(statement)  # type: ignore[arg-type]

    def add(self, instance: object) -> None:
        self._session.add(instance)

    async def flush(self) -> None:
        self._session.flush()

    async def commit(self) -> None:
        self._session.commit()

    async def delete(self, instance: object) -> None:
        self._session.delete(instance)


def _sqlite_schema() -> list[Table]:
    """Les tables utiles, transposées pour SQLite (identifiants auto-numérotés)."""
    miroir = MetaData()
    for table in Base.metadata.tables.values():
        table.to_metadata(miroir)

    utiles = []
    for nom in (
        "classes",
        "subjects",
        "rooms",
        "teacher_profiles",
        "timetable_slots",
        "teacher_availabilities",
        "audit_logs",
    ):
        table = miroir.tables[nom]
        table.c.id.type = Integer()
        utiles.append(table)
    return utiles


@pytest.fixture
def db() -> Iterator[_AsyncBridge]:
    """Un enseignant, deux classes, une matière — de quoi créer une collision."""
    engine = create_engine("sqlite://")
    for table in _sqlite_schema():
        table.create(engine)

    with Session(engine) as session:
        session.add_all(
            [
                Class(id=SIXIEME_A, name="6eme A", level_id=1, series_id=None),
                Class(id=SIXIEME_B, name="6eme B", level_id=1, series_id=None),
                Subject(id=MATHS, name="Mathematiques", coefficient=4),
                TeacherProfile(
                    id=KOUASSI, user_id=101, first_name="Jean-Baptiste", last_name="Kouassi"
                ),
            ]
        )
        session.commit()
        yield _AsyncBridge(session)


def _creation(classe: int, debut: str, fin: str) -> TimetableSlotCreate:
    return TimetableSlotCreate(
        class_id=classe,
        teacher_id=KOUASSI,
        subject_id=MATHS,
        academic_year_id=ANNEE,
        day=DayOfWeek.MONDAY,
        start_time=debut,
        end_time=fin,
    )


@pytest.mark.asyncio
async def test_cours_ailleurs_nomme_la_classe_et_l_heure(db: _AsyncBridge) -> None:
    """Le refus dit avec quelle classe et à quelle heure l'enseignant est pris."""
    db.add(
        TimetableSlot(
            id=1,
            class_id=SIXIEME_B,
            teacher_id=KOUASSI,
            subject_id=MATHS,
            academic_year_id=ANNEE,
            day=DayOfWeek.MONDAY.value,
            start_time=time(8, 0),
            end_time=time(10, 0),
        )
    )
    await db.commit()

    with pytest.raises(ConflictError) as erreur:
        await svc.create_slot(db, _creation(SIXIEME_A, "09:00", "11:00"), created_by=1)  # type: ignore[arg-type]

    message = erreur.value.detail
    assert "Jean-Baptiste Kouassi" in message
    assert "6eme B" in message
    assert "lundi" in message
    assert "08:00 à 10:00" in message


@pytest.mark.asyncio
async def test_indisponibilite_declaree_se_dit_autrement(db: _AsyncBridge) -> None:
    """Une plage fermée par l'enseignant ne se confond pas avec un cours."""
    db.add(
        TeacherAvailability(
            id=1,
            teacher_id=KOUASSI,
            day=DayOfWeek.MONDAY.value,
            start_time=time(15, 0),
            end_time=time(16, 0),
            available=False,
        )
    )
    await db.commit()

    with pytest.raises(ConflictError) as erreur:
        await svc.create_slot(db, _creation(SIXIEME_A, "15:30", "17:00"), created_by=1)  # type: ignore[arg-type]

    message = erreur.value.detail
    assert "Jean-Baptiste Kouassi" in message
    assert "indisponible" in message
    assert "lundi" in message
    assert "15:00 à 16:00" in message
    assert "6eme" not in message  # aucune classe n'est en cause ici


@pytest.mark.asyncio
async def test_plage_ouverte_ne_bloque_pas(db: _AsyncBridge) -> None:
    """Déclarer une disponibilité n'a jamais empêché de poser un cours."""
    db.add(
        TeacherAvailability(
            id=1,
            teacher_id=KOUASSI,
            day=DayOfWeek.MONDAY.value,
            start_time=time(8, 0),
            end_time=time(12, 0),
            available=True,
        )
    )
    await db.commit()

    cree = await svc.create_slot(db, _creation(SIXIEME_A, "09:00", "10:00"), created_by=1)  # type: ignore[arg-type]

    assert (cree.class_name, cree.start_time, cree.end_time) == ("6eme A", "09:00", "10:00")


@pytest.mark.asyncio
async def test_hors_des_plages_declarees_refuse(db: _AsyncBridge) -> None:
    """Des qu'un enseignant a declare une plage, le reste se ferme.

    C'est la regle que suit deja la generation automatique et qu'affiche la
    grille de sa fiche. La saisie manuelle l'ignorait : la grille montrait la
    semaine fermee et la creation passait quand meme.
    """
    db.add(
        TeacherAvailability(
            id=1,
            teacher_id=KOUASSI,
            day=DayOfWeek.MONDAY.value,
            start_time=time(8, 0),
            end_time=time(12, 0),
            available=True,
        )
    )
    await db.commit()

    with pytest.raises(ConflictError) as erreur:
        await svc.create_slot(db, _creation(SIXIEME_A, "14:00", "15:00"), created_by=1)  # type: ignore[arg-type]

    message = erreur.value.detail
    assert "n'est pas déclaré disponible" in message
    assert "14:00 à 15:00" in message
    assert "disponibilités" in message  # dit quoi faire, pas seulement non


@pytest.mark.asyncio
async def test_sans_aucune_declaration_rien_ne_bloque(db: _AsyncBridge) -> None:
    """Un enseignant qui n'a rien declare reste disponible partout."""
    cree = await svc.create_slot(db, _creation(SIXIEME_A, "14:00", "15:00"), created_by=1)  # type: ignore[arg-type]

    assert cree.start_time == "14:00"


@pytest.mark.asyncio
async def test_creneau_adjacent_accepte(db: _AsyncBridge) -> None:
    """Enchaîner deux cours bout à bout n'est pas un chevauchement."""
    db.add(
        TimetableSlot(
            id=1,
            class_id=SIXIEME_B,
            teacher_id=KOUASSI,
            subject_id=MATHS,
            academic_year_id=ANNEE,
            day=DayOfWeek.MONDAY.value,
            start_time=time(8, 0),
            end_time=time(10, 0),
        )
    )
    await db.commit()

    cree = await svc.create_slot(db, _creation(SIXIEME_A, "10:00", "11:00"), created_by=1)  # type: ignore[arg-type]

    assert cree.start_time == "10:00"
