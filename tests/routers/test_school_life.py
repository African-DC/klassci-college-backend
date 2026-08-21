"""Les points d'entrée de la vie scolaire, appelés avec les droits d'un métier réel.

Le billet d'annulation de zéro est signé par l'éducateur et le secrétariat.
Aucun des deux ne lit le cahier de notes, et n'a pas à le lire pour lever un
zéro d'office. Ces tests servent les requêtes avec la matrice de droits de ces
rôles, telle qu'elle est semée, plutôt qu'avec un compte administrateur qui
porte tout le catalogue et ne prouve donc rien.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.core.dependencies import TokenData, get_current_user, get_tenant_db
from app.core.redis import get_redis
from app.main import app
from app.routers import retakes as retakes_router
from app.routers import summons as summons_router
from app.services.tenants.permissions import ROLE_DEFINITIONS

MOCK_USER = TokenData(user_id=7, tenant_id="local", email="educateur@college.ci")

EDUCATOR_PERMISSIONS = frozenset(ROLE_DEFINITIONS["educator"]["permissions"])
SECRETARIAT_PERMISSIONS = frozenset(ROLE_DEFINITIONS["staff"]["permissions"])


@contextmanager
def _client(granted: frozenset[str]) -> Iterator[TestClient]:
    """Client dont la matrice de droits est exactement celle d'un rôle.

    La vraie dépendance `require_permission` reste en place : c'est la lecture
    de la matrice qui est simulée, pas la vérification. Sans quoi le test ne
    dirait rien sur les permissions.
    """
    app.dependency_overrides[get_current_user] = lambda: MOCK_USER
    app.dependency_overrides[get_tenant_db] = lambda: AsyncMock()
    app.dependency_overrides[get_redis] = lambda: AsyncMock()

    async def _check(_db: object, _user_id: int, slug: str) -> bool:
        return slug in granted

    try:
        with patch(
            "app.repositories.permission_repository.check_user_permission",
            new=AsyncMock(side_effect=_check),
        ):
            yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Le blocage : le guichet ne peut pas lire le cahier de notes
# ---------------------------------------------------------------------------


def test_the_school_life_desk_signs_the_ticket_without_reading_the_grade_book() -> None:
    """Les deux métiers qui délivrent le billet n'ont pas `grades:read`.

    C'est le fait qui rendait l'écran inutilisable : il s'alimentait à des
    points d'entrée gardés par `grades:read`, que seuls l'administrateur et le
    directeur possèdent. La recette est passée parce qu'elle a été faite avec
    un compte administrateur.
    """
    for permissions in (EDUCATOR_PERMISSIONS, SECRETARIAT_PERMISSIONS):
        assert "documents:zero-cancellation" in permissions
        assert "grades:read" not in permissions


def test_an_educator_gets_the_missed_evaluations_of_a_student() -> None:
    """L'appel que l'écran fait maintenant, avec les droits d'un éducateur."""
    targets = [
        {
            "evaluation_id": 7,
            "title": "Devoir de mathématiques",
            "subject_name": "Mathématiques",
            "date": "2026-05-18",
            "coefficient": 2,
            "trimester": 1,
        }
    ]
    with _client(EDUCATOR_PERMISSIONS) as client:
        with patch.object(
            retakes_router.retake_service,
            "list_missed_evaluations",
            new_callable=AsyncMock,
        ) as service:
            service.return_value = targets
            response = client.get(
                "/school-life/students/42/missed-evaluations",
                params={"from": "2026-05-15", "to": "2026-05-22"},
            )

    assert response.status_code == 200, response.text
    assert response.json() == targets
    assert service.await_args.kwargs == {
        "student_id": 42,
        "period_start": date(2026, 5, 15),
        "period_end": date(2026, 5, 22),
    }


def test_missed_evaluations_stays_behind_the_ticket_permission() -> None:
    """Sans le droit du billet, la liste des absences reste fermée."""
    with _client(EDUCATOR_PERMISSIONS - {"documents:zero-cancellation"}) as client:
        response = client.get(
            "/school-life/students/42/missed-evaluations",
            params={"from": "2026-05-15", "to": "2026-05-22"},
        )
    assert response.status_code == 403


def test_missed_evaluations_requires_both_bounds() -> None:
    """Sans fenêtre, la requête ramènerait toute la scolarité de l'élève."""
    with _client(EDUCATOR_PERMISSIONS) as client:
        response = client.get("/school-life/students/42/missed-evaluations")
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Les deux registres sont bornés
# ---------------------------------------------------------------------------


def test_the_retake_register_is_served_as_a_page() -> None:
    with _client(EDUCATOR_PERMISSIONS) as client:
        with patch.object(
            retakes_router.retake_service, "list_authorizations", new_callable=AsyncMock
        ) as service:
            service.return_value = {"items": [], "total": 0, "page": 2, "size": 20}
            response = client.get(
                "/school-life/retake-authorizations",
                params={"academic_year_id": 3, "page": 2, "size": 20},
            )

    assert response.status_code == 200, response.text
    assert response.json() == {"items": [], "total": 0, "page": 2, "size": 20}
    assert service.await_args.kwargs["academic_year_id"] == 3
    assert service.await_args.kwargs["page"] == 2
    assert service.await_args.kwargs["size"] == 20


def test_the_summons_register_is_served_as_a_page() -> None:
    envelope = {
        "items": [],
        "summary": {"total": 900, "attended": 400, "missed": 300, "pending": 200},
        "total": 900,
        "page": 1,
        "size": 20,
    }
    with _client(EDUCATOR_PERMISSIONS) as client:
        with patch.object(
            summons_router.summons_service, "list_register", new_callable=AsyncMock
        ) as service:
            service.return_value = envelope
            response = client.get(
                "/school-life/summons", params={"academic_year_id": 3, "outcome": "missed"}
            )

    assert response.status_code == 200, response.text
    # Le décompte accompagne la page : neuf cents convocations dans l'année,
    # vingt lignes à l'écran.
    assert response.json()["summary"]["total"] == 900
    assert service.await_args.kwargs["academic_year_id"] == 3
    assert service.await_args.kwargs["outcome"] == "missed"
    assert service.await_args.kwargs["size"] == 20


def test_the_registers_refuse_an_unbounded_page_size() -> None:
    """Demander cinq mille lignes d'un coup revient à ne pas paginer."""
    with _client(EDUCATOR_PERMISSIONS) as client:
        assert client.get("/school-life/summons", params={"size": 5000}).status_code == 422
        assert (
            client.get("/school-life/retake-authorizations", params={"size": 5000}).status_code
            == 422
        )
