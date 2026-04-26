"""Tests des endpoints /reports/council-minutes."""

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

SAMPLE_DECISION = {
    "id": 1,
    "student_id": 42,
    "student_name": "Koffi Aya",
    "average": Decimal("14.20"),
    "rank": 1,
    "absence_count": 3,
    "auto_decision": "passage",
    "final_decision": None,
    "override_reason": None,
}

SAMPLE_COUNCIL = {
    "id": 1,
    "class_id": 3,
    "class_name": "Terminale C",
    "academic_year_id": 1,
    "trimester": 1,
    "main_teacher_name": "M. Koné",
    "director_name": "Mme Traoré",
    "dren_name": "M. Diallo",
    "notes": None,
    "generated_at": NOW,
    "is_published": False,
    "decisions": [SAMPLE_DECISION],
    "created_at": NOW,
    "updated_at": NOW,
}


def _override_deps() -> None:
    app.dependency_overrides[get_current_user] = lambda: MOCK_USER
    app.dependency_overrides[get_tenant_db] = lambda: AsyncMock()
    app.dependency_overrides[get_redis] = lambda: AsyncMock()


def _clear_deps() -> None:
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# POST /reports/council-minutes/generate
# ---------------------------------------------------------------------------


def test_generate_council_minutes_success() -> None:
    """POST /reports/council-minutes/generate -> 201 + PV."""
    _override_deps()
    try:
        with patch(
            "app.services.council_service.generate_council_minutes",
            new=AsyncMock(return_value=SAMPLE_COUNCIL),
        ):
            with TestClient(app) as client:
                resp = client.post(
                    "/reports/council-minutes/generate",
                    json={
                        "class_id": 3,
                        "trimester": 1,
                        "academic_year_id": 1,
                        "main_teacher_name": "M. Koné",
                        "director_name": "Mme Traoré",
                        "dren_name": "M. Diallo",
                    },
                )
        assert resp.status_code == 201
        data = resp.json()
        assert data["class_id"] == 3
        assert data["trimester"] == 1
        assert len(data["decisions"]) == 1
        assert data["decisions"][0]["auto_decision"] == "passage"
    finally:
        _clear_deps()


def test_generate_council_minutes_invalid_trimester() -> None:
    """POST /reports/council-minutes/generate with trimester=5 -> 422."""
    _override_deps()
    try:
        with TestClient(app) as client:
            resp = client.post(
                "/reports/council-minutes/generate",
                json={
                    "class_id": 3,
                    "trimester": 5,
                    "academic_year_id": 1,
                },
            )
        assert resp.status_code == 422
    finally:
        _clear_deps()


def test_generate_council_minutes_no_auth() -> None:
    """POST /reports/council-minutes/generate sans token -> 401/403."""
    _clear_deps()
    with TestClient(app) as client:
        resp = client.post(
            "/reports/council-minutes/generate",
            json={"class_id": 3, "trimester": 1, "academic_year_id": 1},
        )
    assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# GET /reports/council-minutes/{class_id}/{trimester}
# ---------------------------------------------------------------------------


def test_get_council_minutes_success() -> None:
    """GET /reports/council-minutes/3/1 -> 200 + PV."""
    _override_deps()
    try:
        with patch(
            "app.services.council_service.get_council_minutes",
            new=AsyncMock(return_value=SAMPLE_COUNCIL),
        ):
            with TestClient(app) as client:
                resp = client.get("/reports/council-minutes/3/1?academic_year_id=1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["class_id"] == 3
        assert data["trimester"] == 1
        assert len(data["decisions"]) == 1
    finally:
        _clear_deps()


def test_get_council_minutes_not_found() -> None:
    """GET /reports/council-minutes/999/1 -> 404."""
    _override_deps()
    try:
        from app.core.exceptions import NotFoundError

        with patch(
            "app.services.council_service.get_council_minutes",
            new=AsyncMock(side_effect=NotFoundError("CouncilMinutes", "class=999/trimester=1")),
        ):
            with TestClient(app) as client:
                resp = client.get("/reports/council-minutes/999/1?academic_year_id=1")
        assert resp.status_code == 404
    finally:
        _clear_deps()


# ---------------------------------------------------------------------------
# GET /reports/council-minutes/{class_id}/{trimester}/pdf
# ---------------------------------------------------------------------------


def test_get_council_minutes_pdf_success() -> None:
    """GET /reports/council-minutes/3/1/pdf -> 200 + placeholder URL."""
    _override_deps()
    try:
        with patch(
            "app.services.council_service.get_council_minutes_pdf",
            new=AsyncMock(
                return_value={
                    "pdf_url": "/reports/council-minutes/3/1/pdf/download",
                    "message": "PDF generation not yet implemented — placeholder URL",
                }
            ),
        ):
            with TestClient(app) as client:
                resp = client.get("/reports/council-minutes/3/1/pdf?academic_year_id=1")
        assert resp.status_code == 200
        data = resp.json()
        assert "pdf_url" in data
    finally:
        _clear_deps()


# ---------------------------------------------------------------------------
# PATCH /reports/council-minutes/decisions/{decision_id}
# ---------------------------------------------------------------------------


def test_override_decision_success() -> None:
    """PATCH /reports/council-minutes/decisions/1 -> 200 + updated decision."""
    _override_deps()
    overridden = {
        **SAMPLE_DECISION,
        "final_decision": "passage",
        "override_reason": "Eleve assidu malgre moyenne faible",
    }
    try:
        with patch(
            "app.services.council_service.override_decision",
            new=AsyncMock(return_value=overridden),
        ):
            with TestClient(app) as client:
                resp = client.patch(
                    "/reports/council-minutes/decisions/1",
                    json={
                        "final_decision": "passage",
                        "override_reason": "Eleve assidu malgre moyenne faible",
                    },
                )
        assert resp.status_code == 200
        data = resp.json()
        assert data["final_decision"] == "passage"
        assert data["override_reason"] is not None
    finally:
        _clear_deps()


def test_override_decision_invalid_decision() -> None:
    """PATCH /reports/council-minutes/decisions/1 with bad decision -> 422."""
    _override_deps()
    try:
        with TestClient(app) as client:
            resp = client.patch(
                "/reports/council-minutes/decisions/1",
                json={
                    "final_decision": "promotion",  # invalid
                    "override_reason": "Some reason",
                },
            )
        assert resp.status_code == 422
    finally:
        _clear_deps()


def test_override_decision_missing_reason() -> None:
    """PATCH /reports/council-minutes/decisions/1 without reason -> 422."""
    _override_deps()
    try:
        with TestClient(app) as client:
            resp = client.patch(
                "/reports/council-minutes/decisions/1",
                json={
                    "final_decision": "passage",
                    # missing override_reason
                },
            )
        assert resp.status_code == 422
    finally:
        _clear_deps()


# ---------------------------------------------------------------------------
# Unit test: get_auto_decision
# ---------------------------------------------------------------------------


def test_get_auto_decision_thresholds() -> None:
    """Verify decision thresholds."""
    from app.services.council_service import get_auto_decision

    assert get_auto_decision(Decimal("15.00")) == "passage"
    assert get_auto_decision(Decimal("10.00")) == "passage"
    assert get_auto_decision(Decimal("9.75")) == "repechage"
    assert get_auto_decision(Decimal("9.50")) == "repechage"
    assert get_auto_decision(Decimal("9.00")) == "redoublement"
    assert get_auto_decision(Decimal("8.50")) == "redoublement"
    assert get_auto_decision(Decimal("8.49")) == "exclusion"
    assert get_auto_decision(Decimal("5.00")) == "exclusion"
    assert get_auto_decision(None) == "exclusion"
