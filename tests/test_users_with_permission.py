"""Qui doit être prévenu : la permission, jamais le nom du rôle.

Une notification de tâche ne s'adresse pas à « la caissière » : elle s'adresse
à quiconque a le droit de faire ce qu'elle annonce. Une école confie
l'encaissement à sa secrétaire, une autre à un caissier, une troisième au
directeur. Coder un nom de rôle ici obligerait à modifier le produit école par
école — et c'est précisément ce que la résolution par permission évite.

Les tests tournent sur SQLite via le module standard : ils exécutent le vrai
SQL du dépôt, jointures comprises, sans base MySQL à provisionner.
"""

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models.permission import Permission, Role, RolePermission, UserRole
from app.models.user import User
from app.repositories import permission_repository

ENCAISSER = "payments:create"
VALIDER = "enrollments:validate"


class _AsyncBridge:
    """L'allure d'une `AsyncSession` sur une session synchrone."""

    def __init__(self, session: Session) -> None:
        self._session = session

    async def execute(self, statement: object) -> object:
        return self._session.execute(statement)  # type: ignore[arg-type]


def _utilisateur(uid: int, email: str, *, actif: bool = True) -> User:
    return User(id=uid, email=email, hashed_password="x", role="staff", is_active=actif)


@pytest.fixture()
def db() -> Iterator[Session]:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(
        engine,
        tables=[
            User.__table__,
            Role.__table__,
            Permission.__table__,
            RolePermission.__table__,
            UserRole.__table__,
        ],
    )
    with Session(engine) as session:
        yield session


def _monter_ecole(session: Session) -> None:
    """Une école où l'encaissement est confié à la secrétaire, pas à un caissier."""
    session.add_all(
        [
            _utilisateur(1, "sophie@ecole.ci"),
            _utilisateur(2, "caissier@ecole.ci"),
            _utilisateur(3, "directeur@ecole.ci"),
            _utilisateur(4, "parti@ecole.ci", actif=False),
            Role(id=10, name="Secrétaire"),
            Role(id=11, name="Directeur"),
            Permission(id=100, slug=ENCAISSER, name="Encaisser"),
            Permission(id=101, slug=VALIDER, name="Valider une inscription"),
            RolePermission(role_id=10, permission_id=100),
            RolePermission(role_id=11, permission_id=100),
            RolePermission(role_id=11, permission_id=101),
            UserRole(id=1, user_id=1, role_id=10),
            UserRole(id=2, user_id=3, role_id=11),
            UserRole(id=3, user_id=4, role_id=10),
        ]
    )
    session.flush()


@pytest.mark.asyncio
async def test_trouve_qui_peut_encaisser_quel_que_soit_son_role(db: Session) -> None:
    _monter_ecole(db)
    ids = await permission_repository.list_user_ids_with_permission(_AsyncBridge(db), ENCAISSER)
    # La secrétaire et le directeur, parce qu'ils en ont le droit. Pas le
    # « caissier », qui porte le nom mais aucun rôle ici.
    assert sorted(ids) == [1, 3]


@pytest.mark.asyncio
async def test_n_ecrit_pas_a_un_compte_desactive(db: Session) -> None:
    _monter_ecole(db)
    ids = await permission_repository.list_user_ids_with_permission(_AsyncBridge(db), ENCAISSER)
    # L'utilisateur 4 a le rôle qu'il faut, mais son compte est fermé :
    # lui adresser la tâche la rendrait invisible à tout le monde.
    assert 4 not in ids


@pytest.mark.asyncio
async def test_ne_compte_qu_une_fois_qui_detient_deux_roles(db: Session) -> None:
    _monter_ecole(db)
    db.add(UserRole(id=99, user_id=3, role_id=10))  # le directeur est aussi secrétaire
    db.flush()
    ids = await permission_repository.list_user_ids_with_permission(_AsyncBridge(db), ENCAISSER)
    assert ids.count(3) == 1


@pytest.mark.asyncio
async def test_rend_une_liste_vide_quand_personne_ne_detient_la_permission(db: Session) -> None:
    _monter_ecole(db)
    ids = await permission_repository.list_user_ids_with_permission(
        _AsyncBridge(db), "permission:inexistante"
    )
    # Vide, pas une erreur : c'est au service d'en faire un avertissement,
    # puisqu'une tâche sans destinataire est un défaut de configuration.
    assert ids == []


@pytest.mark.asyncio
async def test_la_meme_personne_peut_detenir_les_deux_bouts_de_la_chaine(db: Session) -> None:
    _monter_ecole(db)
    pont = _AsyncBridge(db)
    encaissent = await permission_repository.list_user_ids_with_permission(pont, ENCAISSER)
    valident = await permission_repository.list_user_ids_with_permission(pont, VALIDER)
    # Le directeur encaisse et valide : l'interface doit alors lui montrer
    # l'action suivante plutôt que de lui envoyer deux alertes séparées.
    assert 3 in encaissent and 3 in valident
