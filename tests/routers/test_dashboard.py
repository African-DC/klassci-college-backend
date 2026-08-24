"""Tests du router /dashboard — agrégats KPI (summary)."""

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.core.dependencies import TokenData, get_current_user, get_tenant_db
from app.core.redis import get_redis
from app.main import app
from app.schemas.admin import (
    AdminSummaryResponse,
    ClassesSummary,
    EnrollmentsSummary,
    ParentsSummary,
    RoomsSummary,
    StaffSummary,
    SubjectsSummary,
    TeachersSummary,
)

MOCK_USER = TokenData(user_id=1, tenant_id="local", email="admin@college.ci")

SVC = "app.routers.dashboard.admin_service"

SAMPLE_SUMMARY = AdminSummaryResponse(
    classes=ClassesSummary(total=4, enrolled=6, capacity=160, full=0),
    teachers=TeachersSummary(total=3, with_speciality=2, with_phone=3, without_speciality=1),
    staff=StaffSummary(total=2, distinct_positions=2, with_phone=1, without_position=0),
    parents=ParentsSummary(total=5, with_account=3, with_email=4, without_account=2),
    rooms=RoomsSummary(total=4, capacity=160, classrooms=4, classes_without_room=0),
    subjects=SubjectsSummary(unique_names=14, instances=24, without_teacher=6, total_hours=120),
    enrollments=EnrollmentsSummary(total=6, valid=5, pending=1, closed=0),
)


def _override_deps() -> None:
    app.dependency_overrides[get_current_user] = lambda: MOCK_USER
    app.dependency_overrides[get_tenant_db] = lambda: AsyncMock()
    app.dependency_overrides[get_redis] = lambda: AsyncMock()


def _clear_deps() -> None:
    app.dependency_overrides.clear()


def test_dashboard_summary_success() -> None:
    _override_deps()
    try:
        with patch(
            f"{SVC}.get_admin_summary",
            new_callable=AsyncMock,
            return_value=SAMPLE_SUMMARY,
        ):
            with TestClient(app) as client:
                resp = client.get("/dashboard/summary")
    finally:
        _clear_deps()

    assert resp.status_code == 200
    body = resp.json()
    assert body["classes"]["total"] == 4
    assert body["classes"]["enrolled"] == 6
    assert body["enrollments"]["valid"] == 5
    assert body["subjects"]["without_teacher"] == 6
    assert body["parents"]["with_account"] == 3


def test_dashboard_summary_unauthenticated() -> None:
    with TestClient(app) as client:
        resp = client.get("/dashboard/summary")
    assert resp.status_code == 401
