"""Tests des endpoints /notifications."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.core.dependencies import TokenData, get_current_user, get_tenant_db
from app.core.redis import get_redis
from app.main import app
from app.schemas.notification import (
    MarkAllReadResponse,
    NotificationListResponse,
    NotificationResponse,
    UnreadCountResponse,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

NOW = datetime.now(UTC)

SAMPLE_NOTIFICATION = NotificationResponse(
    id=1,
    user_id=1,
    type="system",
    channel="in_app",
    title="Bienvenue",
    body="Bienvenue sur KLASSCI Collège",
    read=False,
    sent_at=NOW,
    read_at=None,
    entity_type=None,
    entity_id=None,
    created_at=NOW,
)

SAMPLE_READ_NOTIFICATION = SAMPLE_NOTIFICATION.model_copy(update={"read": True, "read_at": NOW})

SAMPLE_LIST = NotificationListResponse(
    items=[SAMPLE_NOTIFICATION],
    total=1,
    page=1,
    size=20,
)

MOCK_USER = TokenData(user_id=1, tenant_id="local", email="user@college.ci")


def _override_deps() -> None:
    """Surcharge les dépendances d'auth et DB pour les tests."""
    app.dependency_overrides[get_current_user] = lambda: MOCK_USER
    app.dependency_overrides[get_tenant_db] = lambda: AsyncMock()
    app.dependency_overrides[get_redis] = lambda: AsyncMock()


def _clear_deps() -> None:
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# GET /notifications
# ---------------------------------------------------------------------------


def test_list_notifications_success() -> None:
    """GET /notifications → 200 + liste paginée."""
    _override_deps()
    try:
        with patch(
            "app.routers.notifications.notification_service.list_notifications",
            new_callable=AsyncMock,
            return_value=SAMPLE_LIST,
        ):
            with TestClient(app) as client:
                resp = client.get("/notifications")
    finally:
        _clear_deps()

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["page"] == 1
    assert body["size"] == 20
    assert len(body["items"]) == 1
    assert body["items"][0]["id"] == 1
    assert body["items"][0]["read"] is False


def test_list_notifications_with_filters() -> None:
    """GET /notifications?type=system&read=false → filtres transmis au service."""
    _override_deps()
    try:
        with patch(
            "app.routers.notifications.notification_service.list_notifications",
            new_callable=AsyncMock,
            return_value=SAMPLE_LIST,
        ) as mock_list:
            with TestClient(app) as client:
                resp = client.get("/notifications?type=system&read=false&page=2&size=10")
    finally:
        _clear_deps()

    assert resp.status_code == 200
    mock_list.assert_called_once()
    call_kwargs = mock_list.call_args.kwargs
    assert call_kwargs["user_id"] == 1
    assert call_kwargs["type"] == "system"
    assert call_kwargs["read"] is False
    assert call_kwargs["page"] == 2
    assert call_kwargs["size"] == 10


def test_list_notifications_unauthenticated() -> None:
    """GET /notifications sans token → 401."""
    with TestClient(app) as client:
        resp = client.get("/notifications")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /notifications/count
# ---------------------------------------------------------------------------


def test_get_unread_count_success() -> None:
    """GET /notifications/count → 200 + count."""
    _override_deps()
    try:
        with patch(
            "app.routers.notifications.notification_service.get_unread_count",
            new_callable=AsyncMock,
            return_value=UnreadCountResponse(count=5),
        ):
            with TestClient(app) as client:
                resp = client.get("/notifications/count")
    finally:
        _clear_deps()

    assert resp.status_code == 200
    assert resp.json()["count"] == 5


def test_get_unread_count_unauthenticated() -> None:
    """GET /notifications/count sans token → 401."""
    with TestClient(app) as client:
        resp = client.get("/notifications/count")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# PATCH /notifications/{id}/read
# ---------------------------------------------------------------------------


def test_mark_as_read_success() -> None:
    """PATCH /notifications/1/read → 200 + notification lue."""
    _override_deps()
    try:
        with patch(
            "app.routers.notifications.notification_service.mark_as_read",
            new_callable=AsyncMock,
            return_value=SAMPLE_READ_NOTIFICATION,
        ):
            with TestClient(app) as client:
                resp = client.patch("/notifications/1/read")
    finally:
        _clear_deps()

    assert resp.status_code == 200
    assert resp.json()["read"] is True
    assert resp.json()["read_at"] is not None


def test_mark_as_read_not_found() -> None:
    """PATCH /notifications/999/read → 404."""
    from app.core.exceptions import NotFoundError

    _override_deps()
    try:
        with patch(
            "app.routers.notifications.notification_service.mark_as_read",
            new_callable=AsyncMock,
            side_effect=NotFoundError("Notification", 999),
        ):
            with TestClient(app) as client:
                resp = client.patch("/notifications/999/read")
    finally:
        _clear_deps()

    assert resp.status_code == 404


def test_mark_as_read_forbidden() -> None:
    """PATCH /notifications/2/read d'un autre user → 403."""
    from app.core.exceptions import PermissionDeniedError

    _override_deps()
    try:
        with patch(
            "app.routers.notifications.notification_service.mark_as_read",
            new_callable=AsyncMock,
            side_effect=PermissionDeniedError("Cannot mark another user's notification as read"),
        ):
            with TestClient(app) as client:
                resp = client.patch("/notifications/2/read")
    finally:
        _clear_deps()

    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# POST /notifications/read-all
# ---------------------------------------------------------------------------


def test_mark_all_read_success() -> None:
    """POST /notifications/read-all → 200 + updated count."""
    _override_deps()
    try:
        with patch(
            "app.routers.notifications.notification_service.mark_all_read",
            new_callable=AsyncMock,
            return_value=MarkAllReadResponse(updated=3),
        ):
            with TestClient(app) as client:
                resp = client.post("/notifications/read-all")
    finally:
        _clear_deps()

    assert resp.status_code == 200
    assert resp.json()["updated"] == 3


def test_mark_all_read_unauthenticated() -> None:
    """POST /notifications/read-all sans token → 401."""
    with TestClient(app) as client:
        resp = client.post("/notifications/read-all")
    assert resp.status_code == 401
