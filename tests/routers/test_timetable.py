"""Tests des endpoints /timetable."""

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.core.dependencies import TokenData, get_current_user, get_tenant_db
from app.core.redis import get_redis
from app.main import app
from app.schemas.timetable import (
    GenerateTimetableResponse,
    TaskStatusResponse,
    TeacherAvailabilityResponse,
    TimetableSlotResponse,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_SLOT = TimetableSlotResponse(
    id=1,
    class_id=3,
    class_name="Terminale C",
    teacher_id=7,
    teacher_name="M. Koné",
    subject_id=2,
    subject_name="Mathématiques",
    academic_year_id=1,
    day="monday",
    start_time="08:00",
    end_time="10:00",
    room="Salle 12",
)

SAMPLE_AVAILABILITY = TeacherAvailabilityResponse(
    id=1,
    teacher_id=7,
    day="monday",
    start_time="08:00",
    end_time="17:00",
    available=True,
    preferred=False,
)

MOCK_USER = TokenData(user_id=1, tenant_id="local", email="admin@college.ci")


def _override_deps() -> None:
    app.dependency_overrides[get_current_user] = lambda: MOCK_USER
    app.dependency_overrides[get_tenant_db] = lambda: AsyncMock()
    app.dependency_overrides[get_redis] = lambda: AsyncMock()


def _clear_deps() -> None:
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# GET /timetable
# ---------------------------------------------------------------------------


def test_list_slots_success() -> None:
    """GET /timetable → 200 + liste de créneaux."""
    _override_deps()
    try:
        with patch(
            "app.routers.timetable.timetable_service.list_slots",
            new_callable=AsyncMock,
            return_value=[SAMPLE_SLOT],
        ):
            with TestClient(app) as client:
                resp = client.get("/timetable")
    finally:
        _clear_deps()

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["id"] == 1
    assert body[0]["teacher_name"] == "M. Koné"
    assert body[0]["room"] == "Salle 12"


def test_list_slots_with_filters() -> None:
    """GET /timetable?class_id=3&teacher_id=7 → filtres transmis au service."""
    _override_deps()
    try:
        with patch(
            "app.routers.timetable.timetable_service.list_slots",
            new_callable=AsyncMock,
            return_value=[SAMPLE_SLOT],
        ) as mock_list:
            with TestClient(app) as client:
                resp = client.get("/timetable?class_id=3&teacher_id=7&academic_year_id=1")
    finally:
        _clear_deps()

    assert resp.status_code == 200
    call_kwargs = mock_list.call_args.kwargs
    assert call_kwargs["class_id"] == 3
    assert call_kwargs["teacher_id"] == 7
    assert call_kwargs["academic_year_id"] == 1


def test_list_slots_unauthenticated() -> None:
    """GET /timetable sans token → 401."""
    with TestClient(app) as client:
        resp = client.get("/timetable")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /timetable/slots
# ---------------------------------------------------------------------------


def test_create_slot_success() -> None:
    """POST /timetable/slots → 201 + créneau créé."""
    _override_deps()
    try:
        with patch(
            "app.routers.timetable.timetable_service.create_slot",
            new_callable=AsyncMock,
            return_value=SAMPLE_SLOT,
        ):
            with TestClient(app) as client:
                resp = client.post(
                    "/timetable/slots",
                    json={
                        "class_id": 3,
                        "teacher_id": 7,
                        "subject_id": 2,
                        "academic_year_id": 1,
                        "day": "monday",
                        "start_time": "08:00",
                        "end_time": "10:00",
                        "room": "Salle 12",
                    },
                )
    finally:
        _clear_deps()

    assert resp.status_code == 201
    assert resp.json()["id"] == 1
    assert resp.json()["day"] == "monday"


def test_create_slot_missing_field() -> None:
    """POST /timetable/slots sans day → 422."""
    _override_deps()
    try:
        with TestClient(app) as client:
            resp = client.post(
                "/timetable/slots",
                json={"class_id": 3, "teacher_id": 7, "subject_id": 2},
            )
    finally:
        _clear_deps()

    assert resp.status_code == 422


def test_create_slot_conflict() -> None:
    """POST /timetable/slots avec conflit enseignant → 409."""
    from app.core.exceptions import ConflictError

    _override_deps()
    try:
        with patch(
            "app.routers.timetable.timetable_service.create_slot",
            new_callable=AsyncMock,
            side_effect=ConflictError("Teacher already has a class"),
        ):
            with TestClient(app) as client:
                resp = client.post(
                    "/timetable/slots",
                    json={
                        "class_id": 3,
                        "teacher_id": 7,
                        "subject_id": 2,
                        "academic_year_id": 1,
                        "day": "monday",
                        "start_time": "08:00",
                        "end_time": "10:00",
                    },
                )
    finally:
        _clear_deps()

    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# PATCH /timetable/slots/{id}
# ---------------------------------------------------------------------------


def test_update_slot_success() -> None:
    """PATCH /timetable/slots/1 → 200 + créneau modifié."""
    updated = TimetableSlotResponse(**{**SAMPLE_SLOT.model_dump(), "day": "tuesday"})
    _override_deps()
    try:
        with patch(
            "app.routers.timetable.timetable_service.update_slot",
            new_callable=AsyncMock,
            return_value=updated,
        ):
            with TestClient(app) as client:
                resp = client.patch("/timetable/slots/1", json={"day": "tuesday"})
    finally:
        _clear_deps()

    assert resp.status_code == 200
    assert resp.json()["day"] == "tuesday"


def test_update_slot_not_found() -> None:
    """PATCH /timetable/slots/999 → 404."""
    from app.core.exceptions import NotFoundError

    _override_deps()
    try:
        with patch(
            "app.routers.timetable.timetable_service.update_slot",
            new_callable=AsyncMock,
            side_effect=NotFoundError("TimetableSlot", 999),
        ):
            with TestClient(app) as client:
                resp = client.patch("/timetable/slots/999", json={"day": "tuesday"})
    finally:
        _clear_deps()

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /timetable/slots/{id}
# ---------------------------------------------------------------------------


def test_delete_slot_success() -> None:
    """DELETE /timetable/slots/1 → 204."""
    _override_deps()
    try:
        with patch(
            "app.routers.timetable.timetable_service.delete_slot",
            new_callable=AsyncMock,
            return_value=None,
        ):
            with TestClient(app) as client:
                resp = client.delete("/timetable/slots/1")
    finally:
        _clear_deps()

    assert resp.status_code == 204


def test_delete_slot_not_found() -> None:
    """DELETE /timetable/slots/999 → 404."""
    from app.core.exceptions import NotFoundError

    _override_deps()
    try:
        with patch(
            "app.routers.timetable.timetable_service.delete_slot",
            new_callable=AsyncMock,
            side_effect=NotFoundError("TimetableSlot", 999),
        ):
            with TestClient(app) as client:
                resp = client.delete("/timetable/slots/999")
    finally:
        _clear_deps()

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /timetable/generate
# ---------------------------------------------------------------------------


def test_generate_timetable() -> None:
    """POST /timetable/generate → 202 + task_id."""
    _override_deps()
    try:
        with patch(
            "app.routers.timetable.timetable_service.trigger_generate",
            return_value=GenerateTimetableResponse(task_id="celery-uuid-123"),
        ):
            with TestClient(app) as client:
                resp = client.post(
                    "/timetable/generate",
                    json={
                        "class_id": 3,
                        "academic_year_id": 1,
                        "assignments": [{"teacher_id": 7, "subject_id": 2, "hours_per_week": 4}],
                        "available_slots": [
                            {"day": "monday", "start_time": "08:00", "end_time": "09:00"}
                        ],
                    },
                )
    finally:
        _clear_deps()

    assert resp.status_code == 202
    assert resp.json()["task_id"] == "celery-uuid-123"


# ---------------------------------------------------------------------------
# GET /timetable/tasks/{task_id}
# ---------------------------------------------------------------------------


def test_get_task_status_pending() -> None:
    """GET /timetable/tasks/{id} → statut pending."""
    _override_deps()
    try:
        with patch(
            "app.routers.timetable.timetable_service.get_task_status",
            return_value=TaskStatusResponse(status="pending", result=None),
        ):
            with TestClient(app) as client:
                resp = client.get("/timetable/tasks/celery-uuid-123")
    finally:
        _clear_deps()

    assert resp.status_code == 200
    assert resp.json()["status"] == "pending"
    assert resp.json()["result"] is None


def test_get_task_status_success() -> None:
    """GET /timetable/tasks/{id} → statut success + résultat."""
    _override_deps()
    try:
        with patch(
            "app.routers.timetable.timetable_service.get_task_status",
            return_value=TaskStatusResponse(status="success", result=[SAMPLE_SLOT]),
        ):
            with TestClient(app) as client:
                resp = client.get("/timetable/tasks/celery-uuid-123")
    finally:
        _clear_deps()

    assert resp.status_code == 200
    assert resp.json()["status"] == "success"
    assert len(resp.json()["result"]) == 1


# ---------------------------------------------------------------------------
# Teacher availabilities
# ---------------------------------------------------------------------------


def test_list_teacher_availabilities() -> None:
    """GET /teachers/{id}/availabilities → 200 + liste."""
    _override_deps()
    try:
        with patch(
            "app.routers.timetable.timetable_service.list_teacher_availabilities",
            new_callable=AsyncMock,
            return_value=[SAMPLE_AVAILABILITY],
        ):
            with TestClient(app) as client:
                resp = client.get("/teachers/7/availabilities")
    finally:
        _clear_deps()

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["teacher_id"] == 7


def test_create_teacher_availability() -> None:
    """POST /teachers/{id}/availabilities → 201."""
    _override_deps()
    try:
        with patch(
            "app.routers.timetable.timetable_service.create_teacher_availability",
            new_callable=AsyncMock,
            return_value=SAMPLE_AVAILABILITY,
        ):
            with TestClient(app) as client:
                resp = client.post(
                    "/teachers/7/availabilities",
                    json={"day": "monday", "start_time": "08:00", "end_time": "17:00"},
                )
    finally:
        _clear_deps()

    assert resp.status_code == 201
    assert resp.json()["id"] == 1


def test_delete_teacher_availability() -> None:
    """DELETE /teacher-availabilities/1 → 204."""
    _override_deps()
    try:
        with patch(
            "app.routers.timetable.timetable_service.delete_teacher_availability",
            new_callable=AsyncMock,
            return_value=None,
        ):
            with TestClient(app) as client:
                resp = client.delete("/teacher-availabilities/1")
    finally:
        _clear_deps()

    assert resp.status_code == 204
