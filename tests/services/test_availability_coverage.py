"""Une disponibilité déclarée heure par heure couvre quand même deux heures.

L'écran de saisie des disponibilités est une grille d'heures : cocher « libre
de 8 h à 12 h » écrit quatre lignes d'une heure, pas une ligne de quatre. C'est
la seule façon dont le produit sait les écrire.

Le serveur, lui, cherchait **une seule** ligne couvrant tout le créneau. Un
cours de deux heures ne trouvait donc jamais son compte, et l'enseignant qui
avait pris la peine de se déclarer disponible toute la matinée devenait
impossible à placer plus d'une heure d'affilée — l'exact contraire de ce qu'il
venait de dire.
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
LUNDI = DayOfWeek.MONDAY.value


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


def _sqlite_schema() -> list[Table]:
    miroir = MetaData()
    for table in Base.metadata.tables.values():
        table.to_metadata(miroir)
    tables = []
    for nom in ("teacher_availabilities",):
        t = miroir.tables[nom]
        t.c.id.type = Integer()
        tables.append(t)
    return tables


@pytest.fixture
def db() -> Iterator[_AsyncBridge]:
    engine = create_engine("sqlite://")
    for table in _sqlite_schema():
        table.create(engine)
    with Session(engine) as session:
        yield _AsyncBridge(session)


def _heure_ouverte(av_id: int, heure: int) -> TeacherAvailability:
    """Une case cochée dans la grille : une heure pleine, déclarée ouverte."""
    return TeacherAvailability(
        id=av_id,
        teacher_id=KOUASSI,
        day=LUNDI,
        start_time=time(heure, 0),
        end_time=time(heure + 1, 0),
        available=True,
    )


@pytest.mark.asyncio
async def test_deux_heures_contigues_couvrent_un_cours_de_deux_heures(
    db: _AsyncBridge,
) -> None:
    """Le geste que l'écran produit doit suffire à poser un cours normal."""
    for i, heure in enumerate((8, 9, 10, 11), start=1):
        db.add(_heure_ouverte(i, heure))
    await db.commit()

    for debut, fin in ((time(8, 0), time(10, 0)), (time(9, 0), time(12, 0))):
        empechement = await repo.find_teacher_unavailability(
            db,  # type: ignore[arg-type]
            KOUASSI,
            LUNDI,
            debut,
            fin,
        )
        assert empechement is None, (
            f"{debut:%H:%M}-{fin:%H:%M} refusé alors que l'enseignant s'est déclaré "
            f"disponible de 08:00 à 12:00, heure par heure"
        )


@pytest.mark.asyncio
async def test_un_cours_qui_deborde_reste_refuse(db: _AsyncBridge) -> None:
    """La couverture n'excuse pas ce qui dépasse : 11h-13h sort de la plage."""
    for i, heure in enumerate((8, 9, 10, 11), start=1):
        db.add(_heure_ouverte(i, heure))
    await db.commit()

    empechement = await repo.find_teacher_unavailability(
        db,  # type: ignore[arg-type]
        KOUASSI,
        LUNDI,
        time(11, 0),
        time(13, 0),
    )
    assert empechement is not None
    assert empechement[0] == "not_open"


@pytest.mark.asyncio
async def test_un_trou_dans_les_heures_declarees_bloque(db: _AsyncBridge) -> None:
    """Deux plages séparées ne se recollent pas : 8h-9h et 10h-11h laissent 9h-10h fermé."""
    db.add(_heure_ouverte(1, 8))
    db.add(_heure_ouverte(2, 10))
    await db.commit()

    empechement = await repo.find_teacher_unavailability(
        db,  # type: ignore[arg-type]
        KOUASSI,
        LUNDI,
        time(8, 0),
        time(11, 0),
    )
    assert empechement is not None
    assert empechement[0] == "not_open"


@pytest.mark.asyncio
async def test_une_heure_seule_reste_couverte(db: _AsyncBridge) -> None:
    """Le cas simple ne doit pas régresser."""
    db.add(_heure_ouverte(1, 8))
    await db.commit()

    assert (
        await repo.find_teacher_unavailability(
            db,  # type: ignore[arg-type]
            KOUASSI,
            LUNDI,
            time(8, 0),
            time(9, 0),
        )
        is None
    )
