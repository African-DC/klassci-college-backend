"""Tests de l'endpoint /reports/deep-trimester."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.core.dependencies import TokenData, get_current_user, get_tenant_db
from app.main import app

MOCK_USER = TokenData(user_id=1, tenant_id="local", email="admin@college.ci")


def _client() -> TestClient:
    app.dependency_overrides[get_current_user] = lambda: MOCK_USER
    app.dependency_overrides[get_tenant_db] = lambda: AsyncMock()
    return TestClient(app)


class TestExportDeepReport:
    def teardown_method(self) -> None:
        app.dependency_overrides.clear()

    @patch("app.routers.deep_report.service.build_report_pdf")
    def test_export_renvoie_un_pdf_en_telechargement(self, mock_build: AsyncMock) -> None:
        mock_build.return_value = b"%PDF-1.7 deep"
        response = _client().get("/reports/deep-trimester/1?trimester=1")

        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
        assert "attachment" in response.headers["content-disposition"]
        assert response.content == b"%PDF-1.7 deep"

    @patch("app.routers.deep_report.service.build_report_pdf")
    def test_trimestre_par_defaut_est_le_premier(self, mock_build: AsyncMock) -> None:
        mock_build.return_value = b"%PDF-1.7 deep"
        response = _client().get("/reports/deep-trimester/1")

        assert response.status_code == 200
        assert mock_build.await_args is not None
        assert mock_build.await_args.args[2] == 1

    @patch("app.routers.deep_report.service.build_report_pdf")
    def test_trimestre_hors_bornes_refuse(self, mock_build: AsyncMock) -> None:
        response = _client().get("/reports/deep-trimester/1?trimester=4")

        assert response.status_code == 422
        mock_build.assert_not_called()

    @patch("app.routers.deep_report.service.build_report_pdf")
    def test_annee_inconnue_remonte_en_404(self, mock_build: AsyncMock) -> None:
        from app.core.exceptions import NotFoundError

        mock_build.side_effect = NotFoundError("AcademicYear", 999)
        response = _client().get("/reports/deep-trimester/999")

        assert response.status_code == 404
