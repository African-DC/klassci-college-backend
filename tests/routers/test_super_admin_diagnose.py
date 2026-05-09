"""Tests for /super-admin/diagnose."""

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.core.dependencies import TokenData, get_current_user, get_tenant_db
from app.core.redis import get_redis
from app.main import app

JWT_USER = TokenData(user_id=1, tenant_id="local", email="superadmin@klassci.com")


def _override() -> None:
    app.dependency_overrides[get_current_user] = lambda: JWT_USER
    app.dependency_overrides[get_tenant_db] = lambda: AsyncMock()
    app.dependency_overrides[get_redis] = lambda: AsyncMock()


def _clear() -> None:
    app.dependency_overrides.clear()


def test_diagnose_all_ok() -> None:
    _override()
    payload = {
        "overall": "ok",
        "checks": [
            {"component": "backend", "status": "ok", "message": None},
            {"component": "database", "status": "ok", "message": None},
            {"component": "redis", "status": "ok", "message": None},
            {"component": "smtp", "status": "ok", "message": None},
        ],
        "timestamp": "2026-05-09T12:00:00",
    }
    try:
        with patch(
            "app.routers.super_admin.diagnose.collect_platform_health",
            new_callable=AsyncMock,
            return_value=payload,
        ):
            with TestClient(app) as client:
                resp = client.get("/super-admin/diagnose")
    finally:
        _clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["overall"] == "ok"
    assert len(body["checks"]) == 4
    components = {c["component"] for c in body["checks"]}
    assert components == {"backend", "database", "redis", "smtp"}


def test_diagnose_degraded_when_smtp_unconfigured() -> None:
    _override()
    payload = {
        "overall": "degraded",
        "checks": [
            {"component": "backend", "status": "ok", "message": None},
            {"component": "database", "status": "ok", "message": None},
            {"component": "redis", "status": "ok", "message": None},
            {"component": "smtp", "status": "degraded", "message": "SMTP_HOST not set"},
        ],
        "timestamp": "2026-05-09T12:00:00",
    }
    try:
        with patch(
            "app.routers.super_admin.diagnose.collect_platform_health",
            new_callable=AsyncMock,
            return_value=payload,
        ):
            with TestClient(app) as client:
                resp = client.get("/super-admin/diagnose")
    finally:
        _clear()
    assert resp.status_code == 200
    body = resp.json()
    assert body["overall"] == "degraded"


def test_diagnose_unauthenticated() -> None:
    with TestClient(app) as client:
        resp = client.get("/super-admin/diagnose")
    assert resp.status_code == 401
