"""Tests des endpoints /reports/dren-stats."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.core.dependencies import TokenData, get_current_user, get_tenant_db
from app.main import app
from app.schemas.dren_stats import (
    ClassStats,
    DrenStatsResponse,
    LevelStats,
    SubjectStats,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

MOCK_USER = TokenData(user_id=1, tenant_id="local", email="admin@college.ci")

SAMPLE_STATS = DrenStatsResponse(
    academic_year_id=1,
    academic_year_name="2025-2026",
    total_students=350,
    male_count=180,
    female_count=170,
    success_rate=65.5,
    failure_rate=34.5,
    redoublement_rate=20.0,
    exclusion_rate=14.5,
    levels=[
        LevelStats(
            level_id=1,
            level_name="6ème",
            total_students=120,
            male_count=60,
            female_count=60,
            classes=[
                ClassStats(
                    class_id=1,
                    class_name="6ème A",
                    total_students=40,
                    male_count=20,
                    female_count=20,
                    average=Decimal("12.50"),
                ),
                ClassStats(
                    class_id=2,
                    class_name="6ème B",
                    total_students=40,
                    male_count=22,
                    female_count=18,
                    average=Decimal("11.80"),
                ),
                ClassStats(
                    class_id=3,
                    class_name="6ème C",
                    total_students=40,
                    male_count=18,
                    female_count=22,
                    average=None,
                ),
            ],
        ),
    ],
    subjects=[
        SubjectStats(
            subject_id=1,
            subject_name="Mathématiques",
            overall_average=Decimal("11.20"),
            teacher_count=3,
        ),
        SubjectStats(
            subject_id=2,
            subject_name="Français",
            overall_average=Decimal("12.80"),
            teacher_count=4,
        ),
    ],
)


def _override_deps() -> None:
    app.dependency_overrides[get_current_user] = lambda: MOCK_USER
    app.dependency_overrides[get_tenant_db] = lambda: AsyncMock()


def _clear_deps() -> None:
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Tests — GET /reports/dren-stats/{academic_year_id}
# ---------------------------------------------------------------------------


class TestGetDrenStats:
    """Tests pour l'endpoint GET /reports/dren-stats/{academic_year_id}."""

    def setup_method(self) -> None:
        _override_deps()

    def teardown_method(self) -> None:
        _clear_deps()

    @patch("app.routers.dren_stats.service.get_dren_stats")
    def test_get_dren_stats_success(self, mock_get: AsyncMock) -> None:
        mock_get.return_value = SAMPLE_STATS
        client = TestClient(app)
        response = client.get("/reports/dren-stats/1")
        assert response.status_code == 200
        data = response.json()
        assert data["academic_year_id"] == 1
        assert data["academic_year_name"] == "2025-2026"
        assert data["total_students"] == 350
        assert data["male_count"] == 180
        assert data["female_count"] == 170
        assert data["success_rate"] == 65.5
        assert data["failure_rate"] == 34.5
        assert data["redoublement_rate"] == 20.0
        assert data["exclusion_rate"] == 14.5
        assert len(data["levels"]) == 1
        assert data["levels"][0]["level_name"] == "6ème"
        assert len(data["levels"][0]["classes"]) == 3
        assert len(data["subjects"]) == 2

    @patch("app.routers.dren_stats.service.get_dren_stats")
    def test_get_dren_stats_not_found(self, mock_get: AsyncMock) -> None:
        from app.core.exceptions import NotFoundError

        mock_get.side_effect = NotFoundError("AcademicYear", 999)
        client = TestClient(app)
        response = client.get("/reports/dren-stats/999")
        assert response.status_code == 404

    @patch("app.routers.dren_stats.service.get_dren_stats")
    def test_get_dren_stats_no_bulletins(self, mock_get: AsyncMock) -> None:
        """Rates should be null when no bulletins exist."""
        stats_no_bulletins = DrenStatsResponse(
            academic_year_id=1,
            academic_year_name="2025-2026",
            total_students=100,
            male_count=50,
            female_count=50,
            success_rate=None,
            failure_rate=None,
            redoublement_rate=None,
            exclusion_rate=None,
            levels=[],
            subjects=[],
        )
        mock_get.return_value = stats_no_bulletins
        client = TestClient(app)
        response = client.get("/reports/dren-stats/1")
        assert response.status_code == 200
        data = response.json()
        assert data["success_rate"] is None
        assert data["failure_rate"] is None
        assert data["redoublement_rate"] is None
        assert data["exclusion_rate"] is None


# ---------------------------------------------------------------------------
# Tests — GET /reports/dren-stats/{academic_year_id}/export
# ---------------------------------------------------------------------------


class TestExportDrenStats:
    """Tests pour l'endpoint GET /reports/dren-stats/{academic_year_id}/export."""

    def setup_method(self) -> None:
        _override_deps()

    def teardown_method(self) -> None:
        _clear_deps()

    @patch("app.routers.dren_stats.service.export_dren_stats_pdf")
    def test_export_dren_stats_success(self, mock_export: AsyncMock) -> None:
        mock_export.return_value = b"%PDF-1.7 dren"
        client = TestClient(app)
        response = client.get("/reports/dren-stats/1/export")
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
        assert response.content == b"%PDF-1.7 dren"

    @patch("app.routers.dren_stats.service.export_dren_stats_pdf")
    def test_export_dren_stats_not_found(self, mock_export: AsyncMock) -> None:
        from app.core.exceptions import NotFoundError

        mock_export.side_effect = NotFoundError("AcademicYear", 999)
        client = TestClient(app)
        response = client.get("/reports/dren-stats/999/export")
        assert response.status_code == 404
