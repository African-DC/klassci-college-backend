"""Tests des endpoints /super-admin."""

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.core.dependencies import TokenData, get_current_user, get_tenant_db
from app.core.redis import get_redis
from app.main import app

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MOCK_USER = TokenData(user_id=1, tenant_id="local", email="superadmin@klassci.com")

PROVISION_RESULT = {
    "tenant_slug": "lycee-moderne",
    "database": "lycee-moderne",
    "admin_email": "admin@lycee-moderne.ci",
    "status": "provisioned",
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
    """Surcharge les dépendances d'auth et DB pour les tests."""
    app.dependency_overrides[get_current_user] = lambda: MOCK_USER
    app.dependency_overrides[get_tenant_db] = lambda: AsyncMock()
    app.dependency_overrides[get_redis] = lambda: AsyncMock()


def _clear_deps() -> None:
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# POST /super-admin/tenants
# ---------------------------------------------------------------------------


def test_provision_tenant_success() -> None:
    """POST /super-admin/tenants -> 201 + tenant provisionné."""
    _override_deps()
    try:
        with patch(
            "app.routers.super_admin.tenant_service.provision_tenant",
            new_callable=AsyncMock,
            return_value=PROVISION_RESULT,
        ):
            with TestClient(app) as client:
                resp = client.post("/super-admin/tenants", json=VALID_PAYLOAD)
    finally:
        _clear_deps()

    assert resp.status_code == 201
    body = resp.json()
    assert body["tenant_slug"] == "lycee-moderne"
    assert body["database"] == "lycee-moderne"
    assert body["admin_email"] == "admin@lycee-moderne.ci"
    assert body["status"] == "provisioned"
    assert body["url"] == "https://lycee-moderne.klassci.com"


def test_provision_tenant_invalid_slug() -> None:
    """POST /super-admin/tenants avec slug invalide -> 422."""
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
    """POST /super-admin/tenants avec mot de passe court -> 422."""
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
    """POST /super-admin/tenants avec email invalide -> 422."""
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
    """POST /super-admin/tenants sans token -> 401."""
    with TestClient(app) as client:
        resp = client.post("/super-admin/tenants", json=VALID_PAYLOAD)
    assert resp.status_code == 401


def test_provision_tenant_missing_required_fields() -> None:
    """POST /super-admin/tenants sans champs requis -> 422."""
    _override_deps()
    try:
        with TestClient(app) as client:
            resp = client.post("/super-admin/tenants", json={"tenant_slug": "ab"})
    finally:
        _clear_deps()

    assert resp.status_code == 422
