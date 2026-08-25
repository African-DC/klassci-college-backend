"""Marquer lu ce qui a été vu, et rien d'autre.

Ouvrir la cloche ne veut pas dire avoir tout lu. Le stock contient des
alertes plus bas dans la liste, et d'autres arrivent pendant que le panneau
est ouvert. Les effacer toutes ferait disparaître des tâches que personne n'a
vues — exactement ce qu'un compteur est censé empêcher.

Les tests tournent sur SQLite via le module standard : ils exécutent le vrai
UPDATE du dépôt, filtres compris.
"""

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models.notification import Notification
from app.repositories import notification_repository as repo

MOI = 1
UN_COLLEGUE = 2


class _AsyncBridge:
    def __init__(self, session: Session) -> None:
        self._session = session

    async def execute(self, statement: object) -> object:
        return self._session.execute(statement)  # type: ignore[arg-type]

    async def flush(self) -> None:
        self._session.flush()


def _notif(nid: int, user_id: int, *, lue: bool = False) -> Notification:
    return Notification(
        id=nid,
        user_id=user_id,
        type="enrollment_awaiting_payment",
        channel="in_app",
        title="Versement attendu",
        body="…",
        read=lue,
    )


@pytest.fixture()
def db() -> Iterator[Session]:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[Notification.__table__])
    with Session(engine) as session:
        session.add_all(
            [
                _notif(1, MOI),
                _notif(2, MOI),
                _notif(3, MOI),
                _notif(4, MOI, lue=True),
                _notif(5, UN_COLLEGUE),
            ]
        )
        session.flush()
        yield session


def _non_lues(session: Session, user_id: int) -> list[int]:
    lignes = session.execute(
        select(Notification.id).where(
            Notification.user_id == user_id,
            Notification.read.is_(False),
        )
    ).all()
    return sorted(r[0] for r in lignes)


@pytest.mark.asyncio
async def test_ne_marque_que_ce_qui_a_ete_affiche(db: Session) -> None:
    modifiees = await repo.mark_seen(_AsyncBridge(db), MOI, [1, 2])
    assert modifiees == 2
    # La troisième était plus bas dans la liste : elle reste à voir.
    assert _non_lues(db, MOI) == [3]


@pytest.mark.asyncio
async def test_n_efface_pas_les_alertes_d_un_collegue(db: Session) -> None:
    modifiees = await repo.mark_seen(_AsyncBridge(db), MOI, [5])
    # Sans le filtre sur l'utilisateur, n'importe qui ferait disparaître les
    # tâches d'un autre en envoyant ses identifiants.
    assert modifiees == 0
    assert _non_lues(db, UN_COLLEGUE) == [5]


@pytest.mark.asyncio
async def test_ne_compte_pas_ce_qui_etait_deja_lu(db: Session) -> None:
    modifiees = await repo.mark_seen(_AsyncBridge(db), MOI, [1, 4])
    # Le compteur ne bouge que d'un cran : la 4 était déjà lue.
    assert modifiees == 1


@pytest.mark.asyncio
async def test_une_liste_vide_ne_touche_rien(db: Session) -> None:
    modifiees = await repo.mark_seen(_AsyncBridge(db), MOI, [])
    assert modifiees == 0
    assert _non_lues(db, MOI) == [1, 2, 3]
