"""Tests for /super-admin/tenants/{slug}/{students|teachers|classes}."""

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


def test_list_students_returns_paginated_items() -> None:
    _override()
    students = [
        {"id": 1, "first_name": "Aminata", "last_name": "Traoré", "enrollment_number": "S001"},
        {"id": 2, "first_name": "Bakary", "last_name": "Koné", "enrollment_number": "S002"},
    ]
    try:
        with (
            patch(
                "app.routers.super_admin.tenant_data.list_students",
                new_callable=AsyncMock,
                return_value=students,
            ),
            patch(
                "app.routers.super_admin.tenant_data.count_rows",
                new_callable=AsyncMock,
                return_value=2,
            ),
        ):
            with TestClient(app) as client:
                resp = client.get("/super-admin/tenants/lycee-x/students?limit=50")
    finally:
        _clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert len(body["items"]) == 2
    assert body["items"][0]["first_name"] == "Aminata"


def test_list_teachers_for_unknown_tenant_returns_404() -> None:
    _override()
    from sqlalchemy.exc import OperationalError

    err = OperationalError("stmt", {}, Exception("(1049, \"Unknown database 'ghost'\")"))
    try:
        with patch(
            "app.routers.super_admin.tenant_data.list_teachers",
            new_callable=AsyncMock,
            side_effect=err,
        ):
            with TestClient(app) as client:
                resp = client.get("/super-admin/tenants/ghost/teachers")
    finally:
        _clear()
    assert resp.status_code == 404


def test_list_classes_invalid_slug_400() -> None:
    _override()
    try:
        with TestClient(app) as client:
            resp = client.get("/super-admin/tenants/INVALID%20SLUG/classes")
    finally:
        _clear()
    assert resp.status_code == 400


def test_list_students_unauthenticated() -> None:
    with TestClient(app) as client:
        resp = client.get("/super-admin/tenants/lycee-x/students")
    assert resp.status_code == 401
