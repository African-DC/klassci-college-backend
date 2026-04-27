"""Tests des endpoints /teacher (portail enseignant)."""

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.core.dependencies import TokenData, get_current_user, get_tenant_db
from app.core.redis import get_redis
from app.main import app
from app.schemas.teacher_portal import (
    TeacherClassesListResponse,
    TeacherClassResponse,
    TeacherDashboardStats,
    TeacherNextCourse,
    TeacherScheduleResponse,
    TeacherScheduleSlot,
    TeacherUpcomingEval,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MOCK_USER = TokenData(user_id=10, tenant_id="local", email="teacher@college.ci")

SAMPLE_CLASS = TeacherClassResponse(
    class_id=1,
    class_name="Terminale C",
    level_name="Terminale",
    subject_name="Mathematiques",
    student_count=35,
)

SAMPLE_CLASSES_LIST = TeacherClassesListResponse(
    items=[SAMPLE_CLASS],
    total=1,
)

SAMPLE_SLOT = TeacherScheduleSlot(
    id=1,
    day="monday",
    start_time="08:00:00",
    end_time="10:00:00",
    subject_name="Mathematiques",
    class_name="Terminale C",
    room_name="Salle 101",
)

SAMPLE_SCHEDULE = TeacherScheduleResponse(
    items=[SAMPLE_SLOT],
    total=1,
)

SAMPLE_NEXT_COURSE = TeacherNextCourse(
    subject_name="Mathematiques",
    class_name="Terminale C",
    start_time="08:00",
    end_time="10:00",
    room="Salle 12",
)

SAMPLE_UPCOMING_EVAL = TeacherUpcomingEval(
    id=42,
    title="Devoir n1",
    type="controle",
    date="2026-04-30",
    class_id=1,
    class_name="Terminale C",
    subject_name="Mathematiques",
    graded_students=0,
    total_students=30,
)

SAMPLE_STATS = TeacherDashboardStats(
    teacher_name="Aminata Coulibaly",
    total_classes=3,
    total_students=105,
    next_course=SAMPLE_NEXT_COURSE,
    upcoming_evaluations=[SAMPLE_UPCOMING_EVAL],
)


def _override_deps() -> None:
    """Surcharge les dépendances d'auth et DB pour les tests."""
    app.dependency_overrides[get_current_user] = lambda: MOCK_USER
    app.dependency_overrides[get_tenant_db] = lambda: AsyncMock()
    app.dependency_overrides[get_redis] = lambda: AsyncMock()


def _clear_deps() -> None:
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# GET /teacher/classes
# ---------------------------------------------------------------------------


def test_get_teacher_classes_success() -> None:
    """GET /teacher/classes → 200 + liste des classes."""
    _override_deps()
    try:
        with patch(
            "app.routers.teacher_portal.teacher_portal_service.get_classes",
            new_callable=AsyncMock,
            return_value=SAMPLE_CLASSES_LIST,
        ):
            with TestClient(app) as client:
                resp = client.get("/teacher/classes")
    finally:
        _clear_deps()

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["class_name"] == "Terminale C"
    assert body["items"][0]["student_count"] == 35


def test_get_teacher_classes_not_a_teacher() -> None:
    """GET /teacher/classes sans profil enseignant → 404."""
    from app.core.exceptions import NotFoundError

    _override_deps()
    try:
        with patch(
            "app.routers.teacher_portal.teacher_portal_service.get_classes",
            new_callable=AsyncMock,
            side_effect=NotFoundError("TeacherProfile", 10),
        ):
            with TestClient(app) as client:
                resp = client.get("/teacher/classes")
    finally:
        _clear_deps()

    assert resp.status_code == 404


def test_get_teacher_classes_unauthenticated() -> None:
    """GET /teacher/classes sans token → 401."""
    with TestClient(app) as client:
        resp = client.get("/teacher/classes")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /teacher/schedule
# ---------------------------------------------------------------------------


def test_get_teacher_schedule_success() -> None:
    """GET /teacher/schedule → 200 + emploi du temps."""
    _override_deps()
    try:
        with patch(
            "app.routers.teacher_portal.teacher_portal_service.get_schedule",
            new_callable=AsyncMock,
            return_value=SAMPLE_SCHEDULE,
        ):
            with TestClient(app) as client:
                resp = client.get("/teacher/schedule")
    finally:
        _clear_deps()

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["day"] == "monday"
    assert body["items"][0]["subject_name"] == "Mathematiques"
    assert body["items"][0]["room_name"] == "Salle 101"


def test_get_teacher_schedule_not_a_teacher() -> None:
    """GET /teacher/schedule sans profil enseignant → 404."""
    from app.core.exceptions import NotFoundError

    _override_deps()
    try:
        with patch(
            "app.routers.teacher_portal.teacher_portal_service.get_schedule",
            new_callable=AsyncMock,
            side_effect=NotFoundError("TeacherProfile", 10),
        ):
            with TestClient(app) as client:
                resp = client.get("/teacher/schedule")
    finally:
        _clear_deps()

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /teacher/dashboard
# ---------------------------------------------------------------------------


def test_get_teacher_dashboard_stats_success() -> None:
    """GET /teacher/dashboard → 200 + KPIs."""
    _override_deps()
    try:
        with patch(
            "app.routers.teacher_portal.teacher_portal_service.get_dashboard_stats",
            new_callable=AsyncMock,
            return_value=SAMPLE_STATS,
        ):
            with TestClient(app) as client:
                resp = client.get("/teacher/dashboard")
    finally:
        _clear_deps()

    assert resp.status_code == 200
    body = resp.json()
    assert body["teacher_name"] == "Aminata Coulibaly"
    assert body["total_classes"] == 3
    assert body["total_students"] == 105
    assert body["next_course"]["subject_name"] == "Mathematiques"
    assert len(body["upcoming_evaluations"]) == 1
    assert body["upcoming_evaluations"][0]["id"] == 42


def test_get_teacher_dashboard_stats_not_a_teacher() -> None:
    """GET /teacher/dashboard sans profil enseignant → 404."""
    from app.core.exceptions import NotFoundError

    _override_deps()
    try:
        with patch(
            "app.routers.teacher_portal.teacher_portal_service.get_dashboard_stats",
            new_callable=AsyncMock,
            side_effect=NotFoundError("TeacherProfile", 10),
        ):
            with TestClient(app) as client:
                resp = client.get("/teacher/dashboard")
    finally:
        _clear_deps()

    assert resp.status_code == 404
