"""Les routes de la fiche de renseignements atteignent le bon service.

Le service est remplacé : ce qui est vérifié ici, c'est l'aiguillage (le
chemin littéral `/profiles/batch` n'est pas avalé par `/{enrollment_id}`) et
la validation du corps. Le comportement est testé sur base dans
`tests/services/`.
"""

from collections.abc import Iterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.dependencies import TokenData, get_current_user, get_tenant_db
from app.core.redis import get_redis
from app.main import app
from app.schemas.class_information_sheet import InformationSheetResponse, InformationSheetYear
from app.schemas.enrollment import EnrollmentResponse

NOW = datetime.now(UTC)
ENROLLMENT = EnrollmentResponse(
    id=5,
    student_id=42,
    class_id=3,
    academic_year_id=1,
    academic_year_name="2026-2027",
    status="valide",
    fee_variant_id=None,
    notes=None,
    created_by=1,
    created_at=NOW,
    updated_at=NOW,
    lv2="espagnol",
)


#: Les droits accordés à l'appelant du test. Remplacé test par test.
_GRANTED: set[str] = set()


async def _resolve(_user: object, _db: object, slug: str) -> bool:
    """La matrice des droits, réduite à un ensemble : la garde est réellement évaluée.

    Une base `AsyncMock` rendrait une coroutine à `result.scalar()`, toujours
    vraie : toute route passerait, et un 403 ne pourrait jamais être observé.
    """
    return slug in _GRANTED


@pytest.fixture()
def client() -> Iterator[TestClient]:
    _GRANTED.clear()
    _GRANTED.update({"enrollments:read", "enrollments:update", "scholarships:manage"})
    app.dependency_overrides[get_current_user] = lambda: TokenData(
        user_id=7, tenant_id="local", email="compta@college.ci"
    )
    app.dependency_overrides[get_tenant_db] = lambda: AsyncMock()
    app.dependency_overrides[get_redis] = lambda: AsyncMock()
    try:
        with (
            patch("app.core.dependencies.resolve_permission", _resolve),
            TestClient(app) as test_client,
        ):
            yield test_client
    finally:
        app.dependency_overrides.clear()
        _GRANTED.clear()


def test_le_lot_atteint_le_service_du_lot(client: TestClient) -> None:
    service = AsyncMock(return_value={"updated": 2})
    with patch(
        "app.routers.enrollment_profile.enrollment_profile_update.update_profiles_in_batch",
        service,
    ):
        resp = client.patch(
            "/enrollments/profiles/batch",
            json={"items": [{"enrollment_id": 1, "lv2": "allemand"}, {"enrollment_id": 2}]},
        )

    assert resp.status_code == 200
    assert resp.json() == {"updated": 2}
    assert service.call_args.kwargs["updated_by"] == 7


def test_la_fiche_d_une_inscription_rend_l_inscription(client: TestClient) -> None:
    service = AsyncMock(return_value=ENROLLMENT)
    with patch("app.routers.enrollment_profile.enrollment_profile_update.update_profile", service):
        resp = client.patch("/enrollments/5/profile", json={"lv2": "espagnol"})

    assert resp.status_code == 200
    assert resp.json()["lv2"] == "espagnol"
    assert resp.json()["scholarship"] is None
    assert service.call_args.args[1] == 5


def test_une_valeur_hors_liste_est_refusee(client: TestClient) -> None:
    resp = client.patch("/enrollments/5/profile", json={"lv2": "anglais"})

    assert resp.status_code == 422


def test_la_fiche_de_l_ecole_atteint_son_service(client: TestClient) -> None:
    vide = InformationSheetResponse(
        academic_year=InformationSheetYear(id=2, name="2026-2027"), classes=[]
    )
    service = AsyncMock(return_value=vide)
    with patch("app.routers.class_information_sheet.class_information_sheet.school_sheet", service):
        resp = client.get("/information-sheet?academic_year_id=2")

    assert resp.status_code == 200
    assert resp.json() == {"academic_year": {"id": 2, "name": "2026-2027"}, "classes": []}
    assert service.call_args.args[1] == 2


@pytest.mark.parametrize(
    ("method", "url", "body", "missing", "target"),
    [
        (
            "put",
            "/enrollments/5/scholarship",
            {"kind": "demi_bourse"},
            "scholarships:manage",
            "app.routers.enrollment_profile.enrollment_scholarship.upsert_scholarship",
        ),
        (
            "delete",
            "/enrollments/5/scholarship",
            None,
            "scholarships:manage",
            "app.routers.enrollment_profile.enrollment_scholarship.delete_scholarship",
        ),
        (
            "get",
            "/information-sheet",
            None,
            "enrollments:read",
            "app.routers.class_information_sheet.class_information_sheet.school_sheet",
        ),
        (
            "get",
            "/classes/3/information-sheet",
            None,
            "enrollments:read",
            "app.routers.class_information_sheet.class_information_sheet.class_sheet",
        ),
        (
            "patch",
            "/enrollments/5/profile",
            {"lv2": "espagnol"},
            "enrollments:update",
            "app.routers.enrollment_profile.enrollment_profile_update.update_profile",
        ),
        (
            "patch",
            "/enrollments/profiles/batch",
            {"items": [{"enrollment_id": 1}]},
            "enrollments:update",
            "app.routers.enrollment_profile.enrollment_profile_update.update_profiles_in_batch",
        ),
    ],
)
def test_sans_le_droit_la_route_repond_403_sans_toucher_au_service(
    client: TestClient,
    method: str,
    url: str,
    body: dict[str, object] | None,
    missing: str,
    target: str,
) -> None:
    _GRANTED.discard(missing)
    service = AsyncMock()
    with patch(target, service):
        kwargs = {"json": body} if body is not None else {}
        resp = client.request(method.upper(), url, **kwargs)

    assert resp.status_code == 403
    assert missing in resp.json()["detail"]
    service.assert_not_called()


def test_avec_le_droit_la_bourse_se_retire(client: TestClient) -> None:
    service = AsyncMock(return_value=None)
    with patch("app.routers.enrollment_profile.enrollment_scholarship.delete_scholarship", service):
        resp = client.delete("/enrollments/5/scholarship")

    assert resp.status_code == 204
    assert service.call_args.kwargs["actor"] == 7
