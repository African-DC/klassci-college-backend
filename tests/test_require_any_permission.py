"""Un geste, deux métiers : régénérer les frais d'une inscription.

La comptabilité le déclenche depuis la fiche élève, le secrétariat depuis le
dossier d'inscription — et depuis que corriger le profil « nouvel élève »
rejoue la grille, c'est le secrétariat qui en a le plus besoin. N'accepter que
`admin:students:update` laissait son propre bouton en échec, avec un message
qui lui demandait un droit qu'on ne lui donnera pas.

`require_any_permission` laisse passer qui détient l'un OU l'autre, sans jamais
faire une seconde lecture de la matrice des droits : elle s'appuie sur
`_resolve_permission`, comme `require_permission`.

La matrice tourne sur SQLite via le module standard : le vrai SQL du dépôt,
jointures comprises, sans base MySQL à provisionner.
"""

from collections.abc import Awaitable, Callable, Iterator
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.core.dependencies import TokenData, require_any_permission
from app.core.exceptions import PermissionDeniedError
from app.models.permission import Permission, Role, RolePermission, UserRole
from app.models.user import User

SECRETARIAT = "enrollments:update"
COMPTABILITE = "admin:students:update"
AUTRE_CHOSE = "enrollments:read"

ROUTE = "/admin/enrollments/1/regenerate-fees"
SERVICE = "app.services.enrollment_fees.regenerate_enrollment_fees"

SECRETAIRE = 1
COMPTABLE = 2
SURVEILLANT = 3


class _AsyncBridge:
    """L'allure d'une `AsyncSession` sur une session synchrone."""

    def __init__(self, session: Session) -> None:
        self._session = session

    async def execute(self, statement: object) -> object:
        return self._session.execute(statement)  # type: ignore[arg-type]


class _TransactionFactice:
    """Remplace `db.begin_nested()` : un `async with` qui ne fait rien."""

    async def __aenter__(self) -> "_TransactionFactice":
        return self

    async def __aexit__(self, *exc_info: object) -> bool:
        return False


def _garde() -> Callable[..., Awaitable[None]]:
    """La dépendance FastAPI, dépouillée de son enveloppe `Depends`."""
    garde: Callable[..., Awaitable[None]] = require_any_permission(
        SECRETARIAT, COMPTABILITE
    ).dependency
    return garde


@pytest.fixture
def matrice() -> Iterator[_AsyncBridge]:
    """Une école où les deux droits vivent dans deux rôles différents."""
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
        session.add_all(
            [
                User(id=SECRETAIRE, email="sophie@ecole.ci", hashed_password="x", role="staff"),
                User(id=COMPTABLE, email="compta@ecole.ci", hashed_password="x", role="staff"),
                User(id=SURVEILLANT, email="surv@ecole.ci", hashed_password="x", role="staff"),
                Role(id=10, name="Secretariat"),
                Role(id=11, name="Comptabilite"),
                Role(id=12, name="Surveillance"),
                Permission(id=100, slug=SECRETARIAT, name="Modifier une inscription"),
                Permission(id=101, slug=COMPTABILITE, name="Modifier un eleve"),
                Permission(id=102, slug=AUTRE_CHOSE, name="Lire les inscriptions"),
                RolePermission(role_id=10, permission_id=100),
                RolePermission(role_id=11, permission_id=101),
                RolePermission(role_id=12, permission_id=102),
                UserRole(id=1, user_id=SECRETAIRE, role_id=10),
                UserRole(id=2, user_id=COMPTABLE, role_id=11),
                UserRole(id=3, user_id=SURVEILLANT, role_id=12),
            ]
        )
        session.flush()
        yield _AsyncBridge(session)

    engine.dispose()


def _jwt(user_id: int) -> TokenData:
    return TokenData(user_id=user_id, tenant_id="local", email="x@ecole.ci")


def _pat(*scopes: str) -> TokenData:
    return TokenData(
        user_id=SECRETAIRE,
        tenant_id="local",
        email="x@ecole.ci",
        auth_method="pat",
        pat_id=7,
        pat_scopes=list(scopes),
    )


# ---------------------------------------------------------------------------
# La matrice rôle / permission
# ---------------------------------------------------------------------------


async def test_le_secretariat_passe_avec_son_seul_droit(matrice: _AsyncBridge) -> None:
    """Il n'a que `enrollments:update`, et c'est suffisant."""
    assert await _garde()(_jwt(SECRETAIRE), matrice) is None


async def test_la_comptabilite_passe_avec_l_autre_droit(matrice: _AsyncBridge) -> None:
    """L'élargissement ne retire l'accès à personne : qui l'avait le garde."""
    assert await _garde()(_jwt(COMPTABLE), matrice) is None


async def test_qui_ne_detient_aucun_des_deux_est_refuse(matrice: _AsyncBridge) -> None:
    """Un droit voisin ne suffit pas : lire n'est pas régénérer."""
    with pytest.raises(PermissionDeniedError):
        await _garde()(_jwt(SURVEILLANT), matrice)


async def test_le_refus_nomme_les_deux_droits_acceptes(matrice: _AsyncBridge) -> None:
    """N'en citer qu'un enverrait la personne réclamer le mauvais."""
    with pytest.raises(PermissionDeniedError) as refus:
        await _garde()(_jwt(SURVEILLANT), matrice)

    assert SECRETARIAT in refus.value.detail
    assert COMPTABILITE in refus.value.detail


def test_une_garde_sans_permission_est_un_defaut_de_programmation() -> None:
    """Une liste vide laisserait passer tout le monde en silence."""
    with pytest.raises(ValueError):
        require_any_permission()


# ---------------------------------------------------------------------------
# Les jetons personnels : le scope, pas la matrice
# ---------------------------------------------------------------------------


async def test_un_pat_qui_porte_l_un_des_scopes_passe(matrice: _AsyncBridge) -> None:
    assert await _garde()(_pat(SECRETARIAT), matrice) is None


async def test_un_pat_sans_aucun_des_scopes_lit_ce_qui_lui_manque(
    matrice: _AsyncBridge,
) -> None:
    """Un jeton refusé doit pouvoir être corrigé sans ouvrir le code."""
    with pytest.raises(PermissionDeniedError) as refus:
        await _garde()(_pat(AUTRE_CHOSE), matrice)

    assert "PAT scope missing" in refus.value.detail
    assert SECRETARIAT in refus.value.detail
    assert COMPTABILITE in refus.value.detail


# ---------------------------------------------------------------------------
# L'endpoint lui-même
# ---------------------------------------------------------------------------


def _appeler(client_as, token: TokenData) -> int:
    db = AsyncMock()
    db.begin_nested = Mock(return_value=_TransactionFactice())
    with (
        patch(SERVICE, new_callable=AsyncMock, return_value={"message": "ok"}),
        client_as(token, db=db) as http,
    ):
        http_client: TestClient = http
        return http_client.post(ROUTE).status_code


def test_regenerer_les_frais_est_ouvert_au_secretariat(client_as) -> None:
    assert _appeler(client_as, _pat(SECRETARIAT)) == 200


def test_regenerer_les_frais_reste_ouvert_a_la_comptabilite(client_as) -> None:
    assert _appeler(client_as, _pat(COMPTABILITE)) == 200


def test_regenerer_les_frais_est_refuse_sans_aucun_des_deux_droits(client_as) -> None:
    assert _appeler(client_as, _pat(AUTRE_CHOSE)) == 403
