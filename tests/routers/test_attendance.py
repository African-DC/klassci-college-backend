"""Tests des endpoints /attendance."""

from datetime import UTC, date, datetime, time
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.core.dependencies import TokenData, get_current_user, get_tenant_db
from app.core.redis import get_redis
from app.main import app
from app.schemas.attendance import (
    AttendanceRecordResponse,
    ClassAttendanceStats,
    SessionResponse,
    StudentAttendanceResponse,
    StudentAttendanceSummary,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

NOW = datetime.now(UTC)

SAMPLE_RECORD = AttendanceRecordResponse(
    id=1,
    student_id=42,
    status="present",
    time_in=time(8, 0),
    time_out=None,
    source="manual",
    notes=None,
    created_at=NOW,
    updated_at=NOW,
)

SAMPLE_SESSION = SessionResponse(
    id=1,
    entity_type="class",
    context_id=3,
    date=date(2026, 2, 16),
    academic_year_id=1,
    records=[SAMPLE_RECORD],
    created_at=NOW,
    updated_at=NOW,
)

SAMPLE_STUDENT_ATTENDANCE = StudentAttendanceResponse(
    items=[SAMPLE_RECORD],
    total=1,
    page=1,
    size=20,
)

SAMPLE_SUMMARY = StudentAttendanceSummary(
    student_id=42,
    first_name="Jean",
    last_name="Dupont",
    present_count=8,
    absent_count=1,
    late_count=1,
    excused_count=0,
    attendance_rate=90.0,
)

SAMPLE_CLASS_STATS = ClassAttendanceStats(
    class_id=3,
    total_sessions=10,
    attendance_rate=90.0,
    students=[SAMPLE_SUMMARY],
)

MOCK_USER = TokenData(user_id=1, tenant_id="local", email="admin@college.ci")


def _override_deps() -> None:
    """Surcharge les dependances d'auth et DB pour les tests."""
    app.dependency_overrides[get_current_user] = lambda: MOCK_USER
    app.dependency_overrides[get_tenant_db] = lambda: AsyncMock()
    app.dependency_overrides[get_redis] = lambda: AsyncMock()


def _clear_deps() -> None:
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# POST /attendance/sessions
# ---------------------------------------------------------------------------


def test_create_session_success() -> None:
    """POST /attendance/sessions -> 201 + session creee."""
    _override_deps()
    try:
        with patch(
            "app.routers.attendance.attendance_service.create_session",
            new_callable=AsyncMock,
            return_value=SAMPLE_SESSION,
        ):
            with TestClient(app) as client:
                resp = client.post(
                    "/attendance/sessions",
                    json={
                        "entity_type": "class",
                        "context_id": 3,
                        "date": "2026-02-16",
                        "academic_year_id": 1,
                        "records": [{"student_id": 42, "status": "present", "time_in": "08:00:00"}],
                    },
                )
    finally:
        _clear_deps()

    assert resp.status_code == 201
    body = resp.json()
    assert body["id"] == 1
    assert body["entity_type"] == "class"
    assert len(body["records"]) == 1
    assert body["records"][0]["student_id"] == 42


def test_create_session_invalid_entity_type() -> None:
    """POST /attendance/sessions avec entity_type invalide -> 422."""
    _override_deps()
    try:
        with TestClient(app) as client:
            resp = client.post(
                "/attendance/sessions",
                json={
                    "entity_type": "invalid",
                    "context_id": 3,
                    "date": "2026-02-16",
                    "academic_year_id": 1,
                    "records": [{"student_id": 42, "status": "present"}],
                },
            )
    finally:
        _clear_deps()

    assert resp.status_code == 422


def test_create_session_invalid_status() -> None:
    """POST /attendance/sessions avec status invalide -> 422."""
    _override_deps()
    try:
        with TestClient(app) as client:
            resp = client.post(
                "/attendance/sessions",
                json={
                    "entity_type": "class",
                    "context_id": 3,
                    "date": "2026-02-16",
                    "academic_year_id": 1,
                    "records": [{"student_id": 42, "status": "invalid_status"}],
                },
            )
    finally:
        _clear_deps()

    assert resp.status_code == 422


def test_create_session_missing_records() -> None:
    """POST /attendance/sessions sans records -> 422."""
    _override_deps()
    try:
        with TestClient(app) as client:
            resp = client.post(
                "/attendance/sessions",
                json={
                    "entity_type": "class",
                    "context_id": 3,
                    "date": "2026-02-16",
                    "academic_year_id": 1,
                },
            )
    finally:
        _clear_deps()

    assert resp.status_code == 422


def test_create_session_not_found_academic_year() -> None:
    """POST /attendance/sessions avec academic_year invalide -> 422."""
    from app.core.exceptions import BusinessValidationError

    _override_deps()
    try:
        with patch(
            "app.routers.attendance.attendance_service.create_session",
            new_callable=AsyncMock,
            side_effect=BusinessValidationError("AcademicYear 999 not found"),
        ):
            with TestClient(app) as client:
                resp = client.post(
                    "/attendance/sessions",
                    json={
                        "entity_type": "class",
                        "context_id": 3,
                        "date": "2026-02-16",
                        "academic_year_id": 999,
                        "records": [{"student_id": 42, "status": "present"}],
                    },
                )
    finally:
        _clear_deps()

    assert resp.status_code == 422


def test_create_session_unauthenticated() -> None:
    """POST /attendance/sessions sans token -> 401."""
    with TestClient(app) as client:
        resp = client.post(
            "/attendance/sessions",
            json={
                "entity_type": "class",
                "context_id": 3,
                "date": "2026-02-16",
                "academic_year_id": 1,
                "records": [{"student_id": 42, "status": "present"}],
            },
        )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# PATCH /attendance/sessions/{id}
# ---------------------------------------------------------------------------


def test_update_session_success() -> None:
    """PATCH /attendance/sessions/1 -> 200 + session mise a jour."""
    updated = SAMPLE_SESSION.model_copy(
        update={"records": [SAMPLE_RECORD.model_copy(update={"status": "late"})]}
    )
    _override_deps()
    try:
        with patch(
            "app.routers.attendance.attendance_service.update_session",
            new_callable=AsyncMock,
            return_value=updated,
        ):
            with TestClient(app) as client:
                resp = client.patch(
                    "/attendance/sessions/1",
                    json={
                        "records": [{"student_id": 42, "status": "late"}],
                    },
                )
    finally:
        _clear_deps()

    assert resp.status_code == 200
    assert resp.json()["records"][0]["status"] == "late"


def test_update_session_not_found() -> None:
    """PATCH /attendance/sessions/999 -> 404."""
    from app.core.exceptions import NotFoundError

    _override_deps()
    try:
        with patch(
            "app.routers.attendance.attendance_service.update_session",
            new_callable=AsyncMock,
            side_effect=NotFoundError("AttendanceSession", 999),
        ):
            with TestClient(app) as client:
                resp = client.patch(
                    "/attendance/sessions/999",
                    json={"records": [{"student_id": 42, "status": "present"}]},
                )
    finally:
        _clear_deps()

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /attendance/student/{student_id}
# ---------------------------------------------------------------------------


def test_get_student_attendance_success() -> None:
    """GET /attendance/student/42 -> 200 + historique pagine."""
    _override_deps()
    try:
        with patch(
            "app.routers.attendance.attendance_service.get_student_attendance",
            new_callable=AsyncMock,
            return_value=SAMPLE_STUDENT_ATTENDANCE,
        ):
            with TestClient(app) as client:
                resp = client.get("/attendance/student/42")
    finally:
        _clear_deps()

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["page"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["student_id"] == 42


def test_get_student_attendance_with_filters() -> None:
    """GET /attendance/student/42?status=absent&page=2 -> filtre."""
    _override_deps()
    try:
        with patch(
            "app.routers.attendance.attendance_service.get_student_attendance",
            new_callable=AsyncMock,
            return_value=SAMPLE_STUDENT_ATTENDANCE,
        ) as mock_fn:
            with TestClient(app) as client:
                resp = client.get(
                    "/attendance/student/42?status=absent&date_from=2026-01-01&page=2&size=10"
                )
    finally:
        _clear_deps()

    assert resp.status_code == 200
    mock_fn.assert_called_once()
    call_kwargs = mock_fn.call_args.kwargs
    assert call_kwargs["status"] == "absent"
    assert call_kwargs["page"] == 2
    assert call_kwargs["size"] == 10


# ---------------------------------------------------------------------------
# GET /attendance/class/{class_id}/stats
# ---------------------------------------------------------------------------


def test_get_class_stats_success() -> None:
    """GET /attendance/class/3/stats -> 200 + stats."""
    _override_deps()
    try:
        with patch(
            "app.routers.attendance.attendance_service.get_class_stats",
            new_callable=AsyncMock,
            return_value=SAMPLE_CLASS_STATS,
        ):
            with TestClient(app) as client:
                resp = client.get("/attendance/class/3/stats")
    finally:
        _clear_deps()

    assert resp.status_code == 200
    body = resp.json()
    assert body["class_id"] == 3
    assert body["total_sessions"] == 10
    assert body["attendance_rate"] == 90.0
    assert len(body["students"]) == 1
    assert body["students"][0]["student_id"] == 42
    assert body["students"][0]["present_count"] == 8


def test_get_class_stats_with_filters() -> None:
    """GET /attendance/class/3/stats?academic_year_id=1 -> filtre."""
    _override_deps()
    try:
        with patch(
            "app.routers.attendance.attendance_service.get_class_stats",
            new_callable=AsyncMock,
            return_value=SAMPLE_CLASS_STATS,
        ) as mock_fn:
            with TestClient(app) as client:
                resp = client.get("/attendance/class/3/stats?academic_year_id=1")
    finally:
        _clear_deps()

    assert resp.status_code == 200
    mock_fn.assert_called_once()
    call_kwargs = mock_fn.call_args.kwargs
    assert call_kwargs["academic_year_id"] == 1
