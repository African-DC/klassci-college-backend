from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.dependencies import get_tenant_db
from app.core.redis import get_redis
from app.main import app
from app.models.document_issuance import DocumentIssuance
from app.schemas.public_verify import PublicVerificationResponse
from app.services import document_issuance_service as service


def make_issuance(*, status: str = service.STATUS_ACTIVE) -> DocumentIssuance:
    return DocumentIssuance(
        id=9,
        token="token-9",
        cev_code="SNI-AAAA-BBBB-CCCC-DDDD",
        seal_code="SNI-AAAA-BBBB-CCCC-DDDD",
        document_type="bulletin",
        reference="BUL-2026-T3-009",
        student_name="Aminata Traoré",
        class_name="3e A",
        academic_year="2025-2026",
        issued_at=datetime(2026, 7, 21, 12, 0, 0),
        scheme_version=service.SCHEME_CURRENT,
        signature_algorithm=service.SIGNATURE_ALGORITHM,
        key_id="key-2026",
        document_sha256="a" * 64,
        signature="signature",
        status=status,
        revision=1,
    )


def test_public_verification_masks_student_identity() -> None:
    app.dependency_overrides[get_tenant_db] = lambda: AsyncMock()
    redis = AsyncMock()
    redis.eval.return_value = 1
    app.dependency_overrides[get_redis] = lambda: redis
    issuance = make_issuance()
    try:
        with (
            patch(
                "app.routers.public_verify.svc.get_issuance_by_token",
                new=AsyncMock(return_value=issuance),
            ),
            patch("app.routers.public_verify.svc.verify_signature", return_value=True),
            patch(
                "app.routers.public_verify.load_school_settings_for_pdf",
                new=AsyncMock(return_value={"school_name": "Collège Test"}),
            ),
            TestClient(app) as client,
        ):
            response = client.get("/public/verify/local/token-9")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert "student_name" not in response.json()
    assert "reference" not in response.json()
    assert "class_name" not in response.json()
    assert response.json()["valid"] is True
    assert response.headers["cache-control"] == "no-store, private"
    assert set(response.json()) == set(PublicVerificationResponse.model_fields)


def test_revoked_document_is_recognized_but_not_valid() -> None:
    app.dependency_overrides[get_tenant_db] = lambda: AsyncMock()
    redis = AsyncMock()
    redis.eval.return_value = 1
    app.dependency_overrides[get_redis] = lambda: redis
    issuance = make_issuance(status=service.STATUS_REVOKED)
    try:
        with (
            patch(
                "app.routers.public_verify.svc.get_issuance_by_token",
                new=AsyncMock(return_value=issuance),
            ),
            patch("app.routers.public_verify.svc.verify_signature", return_value=True),
            patch(
                "app.routers.public_verify.load_school_settings_for_pdf",
                new=AsyncMock(return_value={"school_name": "Collège Test"}),
            ),
            TestClient(app) as client,
        ):
            response = client.get("/public/verify/local/token-9")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["valid"] is False
    assert response.json()["status"] == "revoked"


def test_uploaded_pdf_integrity_result_is_returned() -> None:
    app.dependency_overrides[get_tenant_db] = lambda: AsyncMock()
    redis = AsyncMock()
    redis.eval.return_value = 1
    app.dependency_overrides[get_redis] = lambda: redis
    issuance = make_issuance()
    try:
        with (
            patch(
                "app.routers.public_verify.svc.get_issuance_by_token",
                new=AsyncMock(return_value=issuance),
            ),
            patch("app.routers.public_verify.svc.verify_signature", return_value=True),
            patch("app.routers.public_verify.svc.matches_pdf_digest", return_value=True),
            patch("app.core.middleware.get_redis_client", return_value=redis),
            TestClient(app) as client,
        ):
            response = client.post(
                "/public/verify-file/local/token-9",
                files={"document": ("bulletin.pdf", b"%PDF-1.7 original", "application/pdf")},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "valid": True,
        "matches": True,
        "status": "matching",
        "signature_valid": True,
        "document_status": "active",
    }


def test_revoked_exact_pdf_is_not_reported_as_modified() -> None:
    app.dependency_overrides[get_tenant_db] = lambda: AsyncMock()
    redis = AsyncMock()
    redis.eval.return_value = 1
    issuance = make_issuance(status=service.STATUS_REVOKED)
    try:
        with (
            patch(
                "app.routers.public_verify.svc.get_issuance_by_token",
                new=AsyncMock(return_value=issuance),
            ),
            patch("app.routers.public_verify.svc.verify_signature", return_value=True),
            patch("app.routers.public_verify.svc.matches_pdf_digest", return_value=True),
            patch("app.core.middleware.get_redis_client", return_value=redis),
            TestClient(app) as client,
        ):
            response = client.post(
                "/public/verify-file/local/token-9",
                files={"document": ("bulletin.pdf", b"%PDF-1.7 original", "application/pdf")},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["matches"] is True
    assert response.json()["valid"] is False
    assert response.json()["document_status"] == "revoked"


def test_public_verification_schema_rejects_identity_fields() -> None:
    with pytest.raises(ValidationError):
        PublicVerificationResponse(
            valid=True,
            status="active",
            scheme="v2",
            document_type="Bulletin",
            issued_at=None,
            expires_at=None,
            school_name="Collège Test",
            signature_algorithm="Ed25519",
            key_id="key-2026",
            file_verification_available=True,
            student_name="Aminata Traore",
        )


def test_upload_rejects_non_pdf() -> None:
    app.dependency_overrides[get_tenant_db] = lambda: AsyncMock()
    redis = AsyncMock()
    redis.eval.return_value = 1
    app.dependency_overrides[get_redis] = lambda: redis
    issuance = make_issuance()
    try:
        with (
            patch(
                "app.routers.public_verify.svc.get_issuance_by_token",
                new=AsyncMock(return_value=issuance),
            ),
            patch("app.routers.public_verify.svc.verify_signature", return_value=True),
            patch("app.core.middleware.get_redis_client", return_value=redis),
            TestClient(app) as client,
        ):
            response = client.post(
                "/public/verify-file/local/token-9",
                files={"document": ("fake.pdf", b"not a pdf", "application/pdf")},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_PDF"


def test_upload_is_rate_limited() -> None:
    app.dependency_overrides[get_tenant_db] = lambda: AsyncMock()
    redis = AsyncMock()
    redis.eval.return_value = 9
    app.dependency_overrides[get_redis] = lambda: redis
    try:
        with (
            patch("app.core.middleware.get_redis_client", return_value=redis),
            TestClient(app) as client,
        ):
            response = client.post(
                "/public/verify-file/local/token-9",
                files={"document": ("bulletin.pdf", b"%PDF-1.7", "application/pdf")},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 429
    assert response.headers["retry-after"] == "60"
