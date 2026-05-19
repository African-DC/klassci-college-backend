"""Tests des endpoints /super-admin/tenants (POST, GET list, GET detail, POST check-slug)."""

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.core.dependencies import TokenData, get_current_user, get_tenant_db
from app.core.redis import get_redis
from app.main import app
from app.services.tenants.exceptions import TenantAlreadyProvisioned

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MOCK_USER = TokenData(user_id=1, tenant_id="local", email="superadmin@klassci.com")

PROVISION_RESULT = {
    "tenant_slug": "lycee-moderne",
    "database": "lycee-moderne",
    "admin_email": "admin@lycee-moderne.ci",
    "status": "provisioned",
    "tenant_url": "https://lycee-moderne.college.klassci.com",
    "welcome_email_sent": False,
}

VALID_PAYLOAD = {
    "tenant_slug": "lycee-moderne",
    "school_name": "Lycée Moderne d'Abidjan",
    "admin_email": "admin@lycee-moderne.ci",
    "admin_password": "SecureP@ss123",
    "school_address": "Abidjan, Cocody",
    "school_phone": "+2250700000000",
}


def _override_deps() -> None:
    app.dependency_overrides[get_current_user] = lambda: MOCK_USER
    app.dependency_overrides[get_tenant_db] = lambda: AsyncMock()
    app.dependency_overrides[get_redis] = lambda: AsyncMock()


def _clear_deps() -> None:
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# POST /super-admin/tenants
# ---------------------------------------------------------------------------


def test_provision_tenant_success() -> None:
    _override_deps()
    try:
        with patch(
            "app.routers.super_admin.tenants.provision_tenant",
            new_callable=AsyncMock,
            return_value=PROVISION_RESULT,
        ):
            with TestClient(app) as client:
                resp = client.post("/super-admin/tenants", json=VALID_PAYLOAD)
    finally:
        _clear_deps()

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["tenant_slug"] == "lycee-moderne"
    assert body["database"] == "lycee-moderne"
    assert body["admin_email"] == "admin@lycee-moderne.ci"
    assert body["status"] == "provisioned"
    assert body["url"] == "https://lycee-moderne.college.klassci.com"


def test_provision_tenant_already_provisioned_returns_409() -> None:
    _override_deps()
    exc = TenantAlreadyProvisioned(
        tenant_slug="lycee-moderne",
        admin_email="admin@lycee-moderne.ci",
        existing_user_id=42,
    )
    try:
        with patch(
            "app.routers.super_admin.tenants.provision_tenant",
            new_callable=AsyncMock,
            side_effect=exc,
        ):
            with TestClient(app) as client:
                resp = client.post("/super-admin/tenants", json=VALID_PAYLOAD)
    finally:
        _clear_deps()

    assert resp.status_code == 409
    assert "already provisioned" in resp.json()["detail"].lower()


def test_provision_tenant_invalid_slug() -> None:
    _override_deps()
    try:
        payload = VALID_PAYLOAD.copy()
        payload["tenant_slug"] = "INVALID SLUG"
        with TestClient(app) as client:
            resp = client.post("/super-admin/tenants", json=payload)
    finally:
        _clear_deps()
    assert resp.status_code == 422


def test_provision_tenant_short_password() -> None:
    _override_deps()
    try:
        payload = VALID_PAYLOAD.copy()
        payload["admin_password"] = "short"
        with TestClient(app) as client:
            resp = client.post("/super-admin/tenants", json=payload)
    finally:
        _clear_deps()
    assert resp.status_code == 422


def test_provision_tenant_invalid_email() -> None:
    _override_deps()
    try:
        payload = VALID_PAYLOAD.copy()
        payload["admin_email"] = "not-an-email"
        with TestClient(app) as client:
            resp = client.post("/super-admin/tenants", json=payload)
    finally:
        _clear_deps()
    assert resp.status_code == 422


def test_provision_tenant_unauthenticated() -> None:
    with TestClient(app) as client:
        resp = client.post("/super-admin/tenants", json=VALID_PAYLOAD)
    assert resp.status_code == 401


def test_provision_tenant_missing_required_fields() -> None:
    _override_deps()
    try:
        with TestClient(app) as client:
            resp = client.post("/super-admin/tenants", json={"tenant_slug": "ab"})
    finally:
        _clear_deps()
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /super-admin/tenants
# ---------------------------------------------------------------------------


def test_list_tenants_returns_overview() -> None:
    _override_deps()
    overview = [
        {
            "slug": "lycee-moderne",
            "url": "https://lycee-moderne.college.klassci.com",
            "db_size_bytes": 12345678,
        },
        {
            "slug": "college-01",
            "url": "https://college-01.college.klassci.com",
            "db_size_bytes": 9876543,
        },
    ]
    try:
        with patch(
            "app.routers.super_admin.tenants.get_tenants_overview",
            new_callable=AsyncMock,
            return_value=overview,
        ):
            with TestClient(app) as client:
                resp = client.get("/super-admin/tenants")
    finally:
        _clear_deps()

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    slugs = [item["slug"] for item in body["items"]]
    assert slugs == ["lycee-moderne", "college-01"]


def test_list_tenants_unauthenticated() -> None:
    with TestClient(app) as client:
        resp = client.get("/super-admin/tenants")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /super-admin/tenants/{slug}
# ---------------------------------------------------------------------------


def test_get_tenant_detail_returns_summary() -> None:
    _override_deps()
    summary = {
        "slug": "lycee-moderne",
        "url": "https://lycee-moderne.college.klassci.com",
        "school_settings": {
            "school_name": "Lycée Moderne",
            "address": "Abidjan",
            "phone": "+225",
            "email": "contact@lycee.ci",
            "ministry_code": "DREN-042",
        },
        "counts": {
            "users": 12,
            "students": 200,
            "teachers": 8,
            "staff": 4,
            "enrollments": 200,
            "payments": 145,
        },
        "alembic_head": "0025",
        "db_size_bytes": 12345678,
    }
    try:
        with patch(
            "app.routers.super_admin.tenants.get_tenant_summary",
            new_callable=AsyncMock,
            return_value=summary,
        ):
            with TestClient(app) as client:
                resp = client.get("/super-admin/tenants/lycee-moderne")
    finally:
        _clear_deps()

    assert resp.status_code == 200
    body = resp.json()
    assert body["slug"] == "lycee-moderne"
    assert body["counts"]["students"] == 200
    assert body["alembic_head"] == "0025"


def test_get_tenant_detail_returns_404_when_missing() -> None:
    _override_deps()
    try:
        with patch(
            "app.routers.super_admin.tenants.get_tenant_summary",
            new_callable=AsyncMock,
            return_value=None,
        ):
            with TestClient(app) as client:
                resp = client.get("/super-admin/tenants/does-not-exist")
    finally:
        _clear_deps()

    assert resp.status_code == 404


def test_get_tenant_detail_rejects_invalid_slug_format() -> None:
    _override_deps()
    try:
        with TestClient(app) as client:
            resp = client.get("/super-admin/tenants/INVALID%20SLUG")
    finally:
        _clear_deps()
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# POST /super-admin/tenants/check-slug
# ---------------------------------------------------------------------------


def test_check_slug_available() -> None:
    _override_deps()
    try:
        with patch(
            "app.routers.super_admin.tenants.slug_exists",
            new_callable=AsyncMock,
            return_value=False,
        ):
            with TestClient(app) as client:
                resp = client.post("/super-admin/tenants/check-slug", json={"slug": "new-school"})
    finally:
        _clear_deps()

    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is True
    assert body["valid_format"] is True
    assert body["reason"] is None


def test_check_slug_taken() -> None:
    _override_deps()
    try:
        with patch(
            "app.routers.super_admin.tenants.slug_exists",
            new_callable=AsyncMock,
            return_value=True,
        ):
            with TestClient(app) as client:
                resp = client.post(
                    "/super-admin/tenants/check-slug", json={"slug": "lycee-moderne"}
                )
    finally:
        _clear_deps()

    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is False
    assert "déjà utilisé" in body["reason"]


def test_check_slug_invalid_format_short_circuits_db() -> None:
    _override_deps()
    try:
        with TestClient(app) as client:
            resp = client.post("/super-admin/tenants/check-slug", json={"slug": "A"})
    finally:
        _clear_deps()

    assert resp.status_code == 200
    body = resp.json()
    assert body["valid_format"] is False
    assert body["available"] is False
