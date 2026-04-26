"""Tests des endpoints /enrollments."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.core.dependencies import TokenData, get_current_user, get_tenant_db
from app.core.redis import get_redis
from app.main import app
from app.schemas.enrollment import EnrollmentListResponse, EnrollmentResponse

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

NOW = datetime.now(UTC)

SAMPLE_ENROLLMENT = EnrollmentResponse(
    id=1,
    student_id=42,
    class_id=3,
    academic_year_id=1,
    academic_year_name="2024-2025",
    status="prospect",
    fee_variant_id=None,
    notes=None,
    created_by=1,
    created_at=NOW,
    updated_at=NOW,
)

SAMPLE_LIST = EnrollmentListResponse(
    items=[SAMPLE_ENROLLMENT],
    total=1,
    page=1,
    size=20,
)

MOCK_USER = TokenData(user_id=1, tenant_id="local", email="admin@college.ci")


def _override_deps() -> None:
    """Surcharge les dépendances d'auth et DB pour les tests."""
    app.dependency_overrides[get_current_user] = lambda: MOCK_USER
    app.dependency_overrides[get_tenant_db] = lambda: AsyncMock()
    app.dependency_overrides[get_redis] = lambda: AsyncMock()


def _clear_deps() -> None:
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# GET /enrollments
# ---------------------------------------------------------------------------


def test_list_enrollments_success() -> None:
    """GET /enrollments → 200 + liste paginée."""
    _override_deps()
    try:
        with patch(
            "app.routers.enrollments.enrollment_service.list_enrollments",
            new_callable=AsyncMock,
            return_value=SAMPLE_LIST,
        ):
            with TestClient(app) as client:
                resp = client.get("/enrollments")
    finally:
        _clear_deps()

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["page"] == 1
    assert body["size"] == 20
    assert len(body["items"]) == 1
    assert body["items"][0]["id"] == 1


def test_list_enrollments_with_filters() -> None:
    """GET /enrollments?class_id=3&status=prospect → filtrés."""
    _override_deps()
    try:
        with patch(
            "app.routers.enrollments.enrollment_service.list_enrollments",
            new_callable=AsyncMock,
            return_value=SAMPLE_LIST,
        ) as mock_list:
            with TestClient(app) as client:
                resp = client.get("/enrollments?class_id=3&status=prospect&page=2&size=10")
    finally:
        _clear_deps()

    assert resp.status_code == 200
    mock_list.assert_called_once()
    call_kwargs = mock_list.call_args.kwargs
    assert call_kwargs["class_id"] == 3
    assert call_kwargs["status"] == "prospect"
    assert call_kwargs["page"] == 2
    assert call_kwargs["size"] == 10


def test_list_enrollments_unauthenticated() -> None:
    """GET /enrollments sans token → 401."""
    with TestClient(app) as client:
        resp = client.get("/enrollments")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /enrollments
# ---------------------------------------------------------------------------


def test_create_enrollment_success() -> None:
    """POST /enrollments → 201 + enrollment créé."""
    _override_deps()
    try:
        with patch(
            "app.routers.enrollments.enrollment_service.create_enrollment",
            new_callable=AsyncMock,
            return_value=SAMPLE_ENROLLMENT,
        ):
            with TestClient(app) as client:
                resp = client.post(
                    "/enrollments",
                    json={"student_id": 42, "class_id": 3, "academic_year_id": 1},
                )
    finally:
        _clear_deps()

    assert resp.status_code == 201
    assert resp.json()["id"] == 1
    assert resp.json()["status"] == "prospect"


def test_create_enrollment_missing_field() -> None:
    """POST /enrollments sans class_id → 422."""
    _override_deps()
    try:
        with TestClient(app) as client:
            resp = client.post(
                "/enrollments",
                json={"student_id": 42},  # missing class_id + academic_year_id
            )
    finally:
        _clear_deps()

    assert resp.status_code == 422


def test_create_enrollment_not_found() -> None:
    """POST /enrollments avec academic_year_id invalide → 422."""
    from app.core.exceptions import BusinessValidationError

    _override_deps()
    try:
        with patch(
            "app.routers.enrollments.enrollment_service.create_enrollment",
            new_callable=AsyncMock,
            side_effect=BusinessValidationError("AcademicYear 999 not found"),
        ):
            with TestClient(app) as client:
                resp = client.post(
                    "/enrollments",
                    json={"student_id": 42, "class_id": 3, "academic_year_id": 999},
                )
    finally:
        _clear_deps()

    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# PATCH /enrollments/{id}
# ---------------------------------------------------------------------------


def test_update_enrollment_success() -> None:
    """PATCH /enrollments/1 → 200 + enrollment mis à jour."""
    updated = SAMPLE_ENROLLMENT.model_copy(update={"status": "valide"})
    _override_deps()
    try:
        with patch(
            "app.routers.enrollments.enrollment_service.update_enrollment",
            new_callable=AsyncMock,
            return_value=updated,
        ):
            with TestClient(app) as client:
                resp = client.patch("/enrollments/1", json={"status": "valide"})
    finally:
        _clear_deps()

    assert resp.status_code == 200
    assert resp.json()["status"] == "valide"


def test_update_enrollment_invalid_status() -> None:
    """PATCH /enrollments/1 avec status invalide → 422."""
    _override_deps()
    try:
        with TestClient(app) as client:
            resp = client.patch("/enrollments/1", json={"status": "unknown_status"})
    finally:
        _clear_deps()

    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# DELETE /enrollments/{id}
# ---------------------------------------------------------------------------


def test_delete_enrollment_success() -> None:
    """DELETE /enrollments/1 → 204."""
    _override_deps()
    try:
        with patch(
            "app.routers.enrollments.enrollment_service.delete_enrollment",
            new_callable=AsyncMock,
            return_value=None,
        ):
            with TestClient(app) as client:
                resp = client.delete("/enrollments/1")
    finally:
        _clear_deps()

    assert resp.status_code == 204


def test_delete_enrollment_not_found() -> None:
    """DELETE /enrollments/999 → 404."""
    from app.core.exceptions import NotFoundError

    _override_deps()
    try:
        with patch(
            "app.routers.enrollments.enrollment_service.delete_enrollment",
            new_callable=AsyncMock,
            side_effect=NotFoundError("Enrollment", 999),
        ):
            with TestClient(app) as client:
                resp = client.delete("/enrollments/999")
    finally:
        _clear_deps()

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /enrollments/{id}
# ---------------------------------------------------------------------------


def test_get_enrollment_success() -> None:
    """GET /enrollments/1 → 200 + enrollment."""
    _override_deps()
    try:
        with patch(
            "app.routers.enrollments.enrollment_service.get_enrollment",
            new_callable=AsyncMock,
            return_value=SAMPLE_ENROLLMENT,
        ):
            with TestClient(app) as client:
                resp = client.get("/enrollments/1")
    finally:
        _clear_deps()

    assert resp.status_code == 200
    assert resp.json()["academic_year_name"] == "2024-2025"


def test_get_enrollment_not_found() -> None:
    """GET /enrollments/999 → 404 (tenant isolation)."""
    from app.core.exceptions import NotFoundError

    _override_deps()
    try:
        with patch(
            "app.routers.enrollments.enrollment_service.get_enrollment",
            new_callable=AsyncMock,
            side_effect=NotFoundError("Enrollment", 999),
        ):
            with TestClient(app) as client:
                resp = client.get("/enrollments/999")
    finally:
        _clear_deps()

    assert resp.status_code == 404
