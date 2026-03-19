"""Tests des endpoints /evaluations, /grades et /bulletins."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from app.core.dependencies import TokenData, get_current_user, get_tenant_db
from app.core.redis import get_redis
from app.main import app

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

NOW = datetime.now(UTC)
TODAY = date.today()

MOCK_USER = TokenData(user_id=1, tenant_id="local", email="admin@college.ci")

SAMPLE_EVAL = {
    "id": 1,
    "title": "Contrôle de Maths T1",
    "type": "controle",
    "date": TODAY,
    "coefficient": 2,
    "subject_id": 2,
    "subject_name": "Mathématiques",
    "class_id": 3,
    "class_name": "Terminale C",
    "teacher_id": 7,
    "teacher_name": "M. Koné",
    "academic_year_id": 1,
    "trimester": 1,
    "total_students": 35,
    "graded_students": 28,
    "created_at": NOW,
}

SAMPLE_GRADES = [
    {"student_id": 42, "student_name": "Koffi Aya", "value": Decimal("14.5"), "status": "entered"},
    {"student_id": 43, "student_name": "Bamba Sidi", "value": None, "status": "pending"},
]

SAMPLE_SUMMARY = {
    "class_id": 3,
    "trimester": 1,
    "students": [
        {
            "student_id": 42,
            "student_name": "Koffi Aya",
            "average": Decimal("14.2"),
            "rank": 1,
            "mention": "B",
        }
    ],
    "subjects": [
        {
            "subject_id": 2,
            "subject_name": "Maths",
            "class_average": Decimal("12.8"),
        }
    ],
}


def _override_deps() -> None:
    app.dependency_overrides[get_current_user] = lambda: MOCK_USER
    app.dependency_overrides[get_tenant_db] = lambda: AsyncMock()
    app.dependency_overrides[get_redis] = lambda: AsyncMock()


def _clear_deps() -> None:
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# GET /evaluations
# ---------------------------------------------------------------------------


def test_list_evaluations_success() -> None:
    """GET /evaluations → 200 + liste."""
    _override_deps()
    try:
        with patch(
            "app.services.grades_service.list_evaluations",
            new=AsyncMock(return_value=[SAMPLE_EVAL]),
        ):
            with TestClient(app) as client:
                resp = client.get("/evaluations?class_id=3")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert data[0]["title"] == "Contrôle de Maths T1"
    finally:
        _clear_deps()


def test_list_evaluations_no_auth() -> None:
    """GET /evaluations sans token → 403 (permission manquante)."""
    _clear_deps()
    with TestClient(app) as client:
        resp = client.get("/evaluations")
    assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# POST /evaluations
# ---------------------------------------------------------------------------


def test_create_evaluation_success() -> None:
    """POST /evaluations → 201 + objet créé avec grades pending."""
    _override_deps()
    try:
        with patch(
            "app.services.grades_service.create_evaluation",
            new=AsyncMock(return_value=SAMPLE_EVAL),
        ):
            with TestClient(app) as client:
                resp = client.post(
                    "/evaluations",
                    json={
                        "title": "Contrôle de Maths T1",
                        "type": "controle",
                        "date": str(TODAY),
                        "coefficient": 2,
                        "subject_id": 2,
                        "class_id": 3,
                        "academic_year_id": 1,
                        "trimester": 1,
                    },
                )
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "Contrôle de Maths T1"
        assert data["total_students"] == 35
    finally:
        _clear_deps()


def test_create_evaluation_invalid_coefficient() -> None:
    """POST /evaluations avec coefficient=0 → 422."""
    _override_deps()
    try:
        with TestClient(app) as client:
            resp = client.post(
                "/evaluations",
                json={
                    "title": "Test",
                    "type": "controle",
                    "date": str(TODAY),
                    "coefficient": 0,
                    "subject_id": 1,
                    "class_id": 1,
                    "academic_year_id": 1,
                    "trimester": 1,
                },
            )
        assert resp.status_code == 422
    finally:
        _clear_deps()


# ---------------------------------------------------------------------------
# GET /grades
# ---------------------------------------------------------------------------


def test_get_grades_success() -> None:
    """GET /grades?evaluation_id=1 → 200 + liste des notes."""
    _override_deps()
    try:
        with patch(
            "app.services.grades_service.get_grades",
            new=AsyncMock(return_value=SAMPLE_GRADES),
        ):
            with TestClient(app) as client:
                resp = client.get("/grades?evaluation_id=1")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["student_id"] == 42
        assert data[1]["status"] == "pending"
    finally:
        _clear_deps()


def test_get_grades_evaluation_not_found() -> None:
    """GET /grades?evaluation_id=999 → 404."""
    _override_deps()
    try:
        from app.core.exceptions import NotFoundError

        with patch(
            "app.services.grades_service.get_grades",
            new=AsyncMock(side_effect=NotFoundError("Evaluation", 999)),
        ):
            with TestClient(app) as client:
                resp = client.get("/grades?evaluation_id=999")
        assert resp.status_code == 404
    finally:
        _clear_deps()


# ---------------------------------------------------------------------------
# PATCH /grades/{evaluation_id}
# ---------------------------------------------------------------------------


def test_batch_update_grades_success() -> None:
    """PATCH /grades/1 → 200 + liste complète mise à jour."""
    _override_deps()
    updated = [
        {
            "student_id": 42,
            "student_name": "Koffi Aya",
            "value": Decimal("14.5"),
            "status": "entered",
        },
        {
            "student_id": 43,
            "student_name": "Bamba Sidi",
            "value": Decimal("12.0"),
            "status": "entered",
        },
    ]
    try:
        with patch(
            "app.services.grades_service.batch_update_grades",
            new=AsyncMock(return_value=updated),
        ):
            with TestClient(app) as client:
                resp = client.patch(
                    "/grades/1",
                    json={
                        "grades": [
                            {"student_id": 42, "value": 14.5},
                            {"student_id": 43, "value": 12.0},
                        ]
                    },
                )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["status"] == "entered"
    finally:
        _clear_deps()


def test_batch_update_grades_invalid_value() -> None:
    """PATCH /grades/1 avec note > 20 → 422."""
    _override_deps()
    try:
        with TestClient(app) as client:
            resp = client.patch(
                "/grades/1",
                json={"grades": [{"student_id": 42, "value": 25.0}]},
            )
        assert resp.status_code == 422
    finally:
        _clear_deps()


# ---------------------------------------------------------------------------
# GET /grades/summary/{class_id}
# ---------------------------------------------------------------------------


def test_get_summary_success() -> None:
    """GET /grades/summary/3 → 200 + moyennes pondérées."""
    _override_deps()
    try:
        with patch(
            "app.services.grades_service.get_summary",
            new=AsyncMock(return_value=SAMPLE_SUMMARY),
        ):
            with TestClient(app) as client:
                resp = client.get("/grades/summary/3?trimester=1&academic_year_id=1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["class_id"] == 3
        assert len(data["students"]) == 1
        assert data["students"][0]["rank"] == 1
        assert data["students"][0]["mention"] == "B"
    finally:
        _clear_deps()


# ---------------------------------------------------------------------------
# POST /bulletins/generate
# ---------------------------------------------------------------------------


def test_generate_bulletins_success() -> None:
    """POST /bulletins/generate → 202 + task_id."""
    _override_deps()
    try:
        mock_response = MagicMock()
        mock_response.task_id = "celery-uuid-123"

        with patch(
            "app.services.grades_service.generate_bulletins",
            new=AsyncMock(return_value={"task_id": "celery-uuid-123"}),
        ):
            with TestClient(app) as client:
                resp = client.post(
                    "/bulletins/generate",
                    json={"class_id": 3, "trimester": 1, "academic_year_id": 1},
                )
        assert resp.status_code == 202
        data = resp.json()
        assert "task_id" in data
    finally:
        _clear_deps()


# ---------------------------------------------------------------------------
# GET /bulletins/tasks/{task_id}
# ---------------------------------------------------------------------------


def test_get_bulletin_task_status_success() -> None:
    """GET /bulletins/tasks/xxx → 200 + status."""
    _override_deps()
    try:
        mock_result = MagicMock()
        mock_result.status = "SUCCESS"
        mock_result.result = {"bulletin_urls": ["https://example.com/bulletin.pdf"]}

        with patch(
            "app.routers.grades.celery_app.AsyncResult",
            return_value=mock_result,
        ):
            with TestClient(app) as client:
                resp = client.get("/bulletins/tasks/celery-uuid-123")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["bulletin_urls"] == ["https://example.com/bulletin.pdf"]
    finally:
        _clear_deps()


def test_get_bulletin_task_status_pending() -> None:
    """GET /bulletins/tasks/xxx → status=pending."""
    _override_deps()
    try:
        mock_result = MagicMock()
        mock_result.status = "PENDING"
        mock_result.result = None

        with patch(
            "app.routers.grades.celery_app.AsyncResult",
            return_value=mock_result,
        ):
            with TestClient(app) as client:
                resp = client.get("/bulletins/tasks/celery-uuid-456")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "pending"
        assert data["bulletin_urls"] is None
    finally:
        _clear_deps()
