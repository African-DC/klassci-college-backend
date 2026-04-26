"""Tests des endpoints /reports/bulletins."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.core.dependencies import TokenData, get_current_user, get_tenant_db
from app.core.redis import get_redis
from app.main import app

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

NOW = datetime.now(UTC)

MOCK_USER = TokenData(user_id=1, tenant_id="local", email="admin@college.ci")

SAMPLE_SUBJECT_AVG = {
    "subject_id": 2,
    "subject_name": "Mathématiques",
    "average": Decimal("14.50"),
    "coefficient": 4,
}

SAMPLE_BULLETIN = {
    "id": 1,
    "student_id": 42,
    "student_name": "Koffi Aya",
    "class_id": 3,
    "class_name": "Terminale C",
    "academic_year_id": 1,
    "trimester": 1,
    "average": Decimal("14.25"),
    "rank": 1,
    "total_students": 35,
    "mention": "B",
    "teacher_comment": None,
    "council_decision": None,
    "file_url": None,
    "generated_at": NOW,
    "is_published": False,
    "subject_averages": [SAMPLE_SUBJECT_AVG],
    "created_at": NOW,
    "updated_at": NOW,
}

SAMPLE_GENERATE_RESPONSE = {
    "message": "Generated 2 bulletins for trimester 1",
    "generated": 2,
    "bulletins": [SAMPLE_BULLETIN],
}

SAMPLE_LIST_RESPONSE = {
    "items": [SAMPLE_BULLETIN],
    "total": 1,
}

SAMPLE_PDF_RESPONSE = {
    "bulletin_id": 1,
    "student_id": 42,
    "pdf_url": "/reports/bulletins/1/download",
}


def _override_deps() -> None:
    app.dependency_overrides[get_current_user] = lambda: MOCK_USER
    app.dependency_overrides[get_tenant_db] = lambda: AsyncMock()
    app.dependency_overrides[get_redis] = lambda: AsyncMock()


def _clear_deps() -> None:
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# POST /reports/bulletins/generate
# ---------------------------------------------------------------------------


def test_generate_bulletins_success() -> None:
    """POST /reports/bulletins/generate → 201 + bulletins generes."""
    _override_deps()
    try:
        with patch(
            "app.services.reports_service.generate_bulletins",
            new=AsyncMock(return_value=SAMPLE_GENERATE_RESPONSE),
        ):
            with TestClient(app) as client:
                resp = client.post(
                    "/reports/bulletins/generate",
                    json={"class_id": 3, "trimester": 1, "academic_year_id": 1},
                )
        assert resp.status_code == 201
        data = resp.json()
        assert data["generated"] == 2
        assert len(data["bulletins"]) == 1
        assert data["bulletins"][0]["student_name"] == "Koffi Aya"
    finally:
        _clear_deps()


def test_generate_bulletins_invalid_trimester() -> None:
    """POST /reports/bulletins/generate avec trimester=4 → 422."""
    _override_deps()
    try:
        with TestClient(app) as client:
            resp = client.post(
                "/reports/bulletins/generate",
                json={"class_id": 3, "trimester": 4, "academic_year_id": 1},
            )
        assert resp.status_code == 422
    finally:
        _clear_deps()


def test_generate_bulletins_no_auth() -> None:
    """POST /reports/bulletins/generate sans token → 401/403."""
    _clear_deps()
    with TestClient(app) as client:
        resp = client.post(
            "/reports/bulletins/generate",
            json={"class_id": 3, "trimester": 1, "academic_year_id": 1},
        )
    assert resp.status_code in (401, 403)


def test_generate_bulletins_no_students() -> None:
    """POST /reports/bulletins/generate sans eleves → 422."""
    _override_deps()
    try:
        from app.core.exceptions import BusinessValidationError

        with patch(
            "app.services.reports_service.generate_bulletins",
            new=AsyncMock(
                side_effect=BusinessValidationError(
                    "No enrolled students found for class 3 / year 1"
                )
            ),
        ):
            with TestClient(app) as client:
                resp = client.post(
                    "/reports/bulletins/generate",
                    json={"class_id": 3, "trimester": 1, "academic_year_id": 1},
                )
        assert resp.status_code == 422
        assert "No enrolled students" in resp.json()["detail"]
    finally:
        _clear_deps()


# ---------------------------------------------------------------------------
# GET /reports/bulletins/{class_id}/{trimester}
# ---------------------------------------------------------------------------


def test_list_bulletins_success() -> None:
    """GET /reports/bulletins/3/1 → 200 + liste des bulletins."""
    _override_deps()
    try:
        with patch(
            "app.services.reports_service.list_bulletins",
            new=AsyncMock(return_value=SAMPLE_LIST_RESPONSE),
        ):
            with TestClient(app) as client:
                resp = client.get("/reports/bulletins/3/1?academic_year_id=1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["rank"] == 1
    finally:
        _clear_deps()


def test_list_bulletins_no_auth() -> None:
    """GET /reports/bulletins/3/1 sans token → 401/403."""
    _clear_deps()
    with TestClient(app) as client:
        resp = client.get("/reports/bulletins/3/1?academic_year_id=1")
    assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# GET /reports/bulletins/{bulletin_id}/pdf
# ---------------------------------------------------------------------------


def test_get_bulletin_pdf_success() -> None:
    """GET /reports/bulletins/1/pdf → 200 + URL PDF."""
    _override_deps()
    try:
        with patch(
            "app.services.reports_service.get_bulletin_pdf",
            new=AsyncMock(return_value=SAMPLE_PDF_RESPONSE),
        ):
            with TestClient(app) as client:
                resp = client.get("/reports/bulletins/1/pdf")
        assert resp.status_code == 200
        data = resp.json()
        assert data["bulletin_id"] == 1
        assert "pdf_url" in data
    finally:
        _clear_deps()


def test_get_bulletin_pdf_not_found() -> None:
    """GET /reports/bulletins/999/pdf → 404."""
    _override_deps()
    try:
        from app.core.exceptions import NotFoundError

        with patch(
            "app.services.reports_service.get_bulletin_pdf",
            new=AsyncMock(side_effect=NotFoundError("Bulletin", 999)),
        ):
            with TestClient(app) as client:
                resp = client.get("/reports/bulletins/999/pdf")
        assert resp.status_code == 404
    finally:
        _clear_deps()
