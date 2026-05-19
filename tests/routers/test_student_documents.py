"""Tests for /students/{id}/documents/* endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.core.dependencies import TokenData, get_current_user, get_tenant_db
from app.core.redis import get_redis
from app.main import app

MOCK_USER = TokenData(user_id=1, tenant_id="local", email="admin@college.ci")


def _override_deps() -> None:
    app.dependency_overrides[get_current_user] = lambda: MOCK_USER
    app.dependency_overrides[get_tenant_db] = lambda: AsyncMock()
    app.dependency_overrides[get_redis] = lambda: AsyncMock()


def _clear_deps() -> None:
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# GET /students/{id}/documents/certificat-scolarite.pdf
# ---------------------------------------------------------------------------


def test_get_certificat_no_auth() -> None:
    """GET /students/1/documents/certificat-scolarite.pdf sans token → 401/403."""
    _clear_deps()
    with TestClient(app) as client:
        resp = client.get("/students/1/documents/certificat-scolarite.pdf")
    assert resp.status_code in (401, 403)


def test_get_certificat_success() -> None:
    """Admin avec permission → 200 + bytes PDF."""
    _override_deps()
    try:
        with (
            patch(
                "app.services.student_documents_service.verify_document_access",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.services.student_documents_service.compose_certificate_data",
                new=AsyncMock(
                    return_value={
                        "student": {
                            "first_name": "Aya",
                            "last_name": "Koffi",
                            "birth_date": None,
                            "genre": "F",
                            "enrollment_number": "2024-001",
                            "city": "Abidjan",
                            "commune": "Cocody",
                        },
                        "class_name": "6e A",
                        "academic_year_name": "2025-2026",
                        "issued_at": None,
                    }
                ),
            ),
            patch(
                "app.routers.student_documents.load_school_settings_for_pdf",
                new=AsyncMock(return_value={"school_name": "Ecole Test"}),
            ),
            patch(
                "app.routers.student_documents.generate_certificate_scolarite_pdf",
                return_value=b"%PDF-1.4 fake bytes",
            ),
        ):
            with TestClient(app) as client:
                resp = client.get("/students/1/documents/certificat-scolarite.pdf")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/pdf"
        assert "Koffi" in resp.headers["content-disposition"]
    finally:
        _clear_deps()


def test_get_certificat_no_active_enrollment() -> None:
    """Pas d'inscription valide → 422 message FR."""
    from app.core.exceptions import BusinessValidationError

    _override_deps()
    try:
        with (
            patch(
                "app.services.student_documents_service.verify_document_access",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.services.student_documents_service.compose_certificate_data",
                new=AsyncMock(
                    side_effect=BusinessValidationError(
                        "Aucune inscription valide trouvée pour cet élève."
                    )
                ),
            ),
        ):
            with TestClient(app) as client:
                resp = client.get("/students/1/documents/certificat-scolarite.pdf")
        assert resp.status_code == 422
        assert "inscription valide" in resp.text.lower() or "inscription" in resp.text.lower()
    finally:
        _clear_deps()
