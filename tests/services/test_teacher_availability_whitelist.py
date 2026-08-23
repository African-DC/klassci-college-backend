"""La liste blanche des disponibilités — ce qui ouvre, et ce qui ne ferme pas.

La table se lit en liste blanche : tant qu'un enseignant n'a rien déclaré, il
est disponible partout ; dès qu'il a déclaré une **ouverture**, seul ce qui est
ouvert reste posable.

Le mot qui compte est « ouverture ». Une plage fermée ne bascule pas la table en
liste blanche — sinon noter une seule absence rendrait l'enseignant
inplaçable toute la semaine, ce qui est exactement l'inverse du geste demandé :
le secrétariat note « il n'est pas là mardi matin » et l'application comprend
« il n'est jamais là ».

Ces tests exécutent la vraie requête sur une vraie base.
"""

from collections.abc import Iterator
from datetime import time

import pytest
from sqlalchemy import Integer, MetaData, Table, create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models.timetable import DayOfWeek, TeacherAvailability
from app.repositories import timetable_repository as repo

KOUASSI = 7


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
    miroir = MetaData()
    for table in Base.metadata.tables.values():
        table.to_metadata(miroir)
    utiles = []
    for nom in ("teacher_availabilities",):
        table = miroir.tables[nom]
        table.c.id.type = Integer()
        utiles.append(table)
    return utiles


def _plage(
    av_id: int, jour: DayOfWeek, debut: time, fin: time, *, ouverte: bool
) -> TeacherAvailability:
    return TeacherAvailability(
        id=av_id,
        teacher_id=KOUASSI,
        day=jour.value,
        start_time=debut,
        end_time=fin,
        available=ouverte,
    )


@pytest.fixture
def db() -> Iterator[_AsyncBridge]:
    engine = create_engine("sqlite://")
    for table in _sqlite_schema():
        table.create(engine)
    with Session(engine) as session:
        yield _AsyncBridge(session)


@pytest.mark.asyncio
async def test_une_absence_ne_ferme_que_son_creneau(db: _AsyncBridge) -> None:
    """Noter « absent mardi matin » ne doit pas fermer le reste de la semaine.

    C'est le geste que la fonctionnalité existe pour permettre : l'enseignant
    prévient de vive voix, le secrétariat le note. Si ce geste ferme les six
    jours, personne ne le fera deux fois.
    """
    db.add(_plage(1, DayOfWeek.TUESDAY, time(8, 0), time(12, 0), ouverte=False))
    await db.commit()

    dedans = await repo.find_teacher_unavailability(
        db,  # type: ignore[arg-type]
        KOUASSI,
        DayOfWeek.TUESDAY.value,
        time(9, 0),
        time(10, 0),
    )
    assert dedans is not None
    assert dedans[0] == "closed"

    for jour, debut, fin in (
        (DayOfWeek.MONDAY, time(8, 0), time(9, 0)),
        (DayOfWeek.TUESDAY, time(14, 0), time(15, 0)),
        (DayOfWeek.FRIDAY, time(15, 0), time(16, 0)),
        (DayOfWeek.SATURDAY, time(7, 0), time(8, 0)),
    ):
        ailleurs = await repo.find_teacher_unavailability(
            db,  # type: ignore[arg-type]
            KOUASSI,
            jour.value,
            debut,
            fin,
        )
        assert ailleurs is None, (
            f"{jour.value} {debut:%H:%M} refusé alors que la seule déclaration "
            f"est une absence le mardi matin : motif « {ailleurs[0] if ailleurs else ''} »"
        )


@pytest.mark.asyncio
async def test_une_ouverture_declaree_ferme_le_reste(db: _AsyncBridge) -> None:
    """Déclarer une ouverture, en revanche, bascule bien en liste blanche."""
    db.add(_plage(1, DayOfWeek.MONDAY, time(8, 0), time(12, 0), ouverte=True))
    await db.commit()

    dedans = await repo.find_teacher_unavailability(
        db,  # type: ignore[arg-type]
        KOUASSI,
        DayOfWeek.MONDAY.value,
        time(9, 0),
        time(10, 0),
    )
    assert dedans is None

    dehors = await repo.find_teacher_unavailability(
        db,  # type: ignore[arg-type]
        KOUASSI,
        DayOfWeek.MONDAY.value,
        time(14, 0),
        time(15, 0),
    )
    assert dehors is not None
    assert dehors[0] == "not_open"

    autre_jour = await repo.find_teacher_unavailability(
        db,  # type: ignore[arg-type]
        KOUASSI,
        DayOfWeek.FRIDAY.value,
        time(9, 0),
        time(10, 0),
    )
    assert autre_jour is not None
    assert autre_jour[0] == "not_open"


@pytest.mark.asyncio
async def test_sans_aucune_declaration_tout_est_ouvert(db: _AsyncBridge) -> None:
    """Le cas de la très grande majorité des enseignants : rien de déclaré."""
    assert (
        await repo.find_teacher_unavailability(
            db,  # type: ignore[arg-type]
            KOUASSI,
            DayOfWeek.MONDAY.value,
            time(9, 0),
            time(10, 0),
        )
        is None
    )


@pytest.mark.asyncio
async def test_une_fermeture_dans_une_semaine_ouverte(db: _AsyncBridge) -> None:
    """Les deux règles cohabitent : la fermeture prime dans son propre créneau."""
    db.add(_plage(1, DayOfWeek.MONDAY, time(8, 0), time(18, 0), ouverte=True))
    db.add(_plage(2, DayOfWeek.MONDAY, time(12, 0), time(14, 0), ouverte=False))
    await db.commit()

    midi = await repo.find_teacher_unavailability(
        db,  # type: ignore[arg-type]
        KOUASSI,
        DayOfWeek.MONDAY.value,
        time(12, 30),
        time(13, 30),
    )
    assert midi is not None
    assert midi[0] == "closed"

    matin = await repo.find_teacher_unavailability(
        db,  # type: ignore[arg-type]
        KOUASSI,
        DayOfWeek.MONDAY.value,
        time(9, 0),
        time(10, 0),
    )
    assert matin is None
