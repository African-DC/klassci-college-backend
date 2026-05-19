"""Tests for /super-admin/pats endpoints."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.core.dependencies import TokenData, get_current_user, get_tenant_db
from app.core.redis import get_redis
from app.main import app
from app.models.personal_access_token import PersonalAccessToken

JWT_USER = TokenData(user_id=1, tenant_id="local", email="superadmin@klassci.com")
PAT_USER = TokenData(
    user_id=1,
    tenant_id="local",
    email="superadmin@klassci.com",
    auth_method="pat",
    pat_id=10,
    pat_scopes=["super-admin:*"],
)


def _override_with(user: TokenData) -> None:
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_tenant_db] = lambda: AsyncMock()
    app.dependency_overrides[get_redis] = lambda: AsyncMock()


def _clear_deps() -> None:
    app.dependency_overrides.clear()


def _make_pat(pat_id: int = 100, *, revoked: bool = False) -> PersonalAccessToken:
    now = datetime.now(UTC).replace(tzinfo=None)
    return PersonalAccessToken(
        id=pat_id,
        name="dev-laptop",
        token_hash="x" * 64,
        token_prefix="klc_pat_abc",
        user_id=1,
        scopes=["super-admin:tenants:read"],
        expires_at=now + timedelta(days=90),
        last_used_at=None,
        revoked_at=now if revoked else None,
        created_at=now,
        updated_at=now,
    )


def test_create_pat_with_jwt_returns_plaintext_once() -> None:
    _override_with(JWT_USER)
    pat = _make_pat()
    try:
        with patch(
            "app.routers.super_admin.pats.create_pat",
            new_callable=AsyncMock,
            return_value=(pat, "klc_pat_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"),
        ):
            with TestClient(app) as client:
                resp = client.post(
                    "/super-admin/pats",
                    json={
                        "name": "dev-laptop",
                        "scopes": ["super-admin:tenants:read"],
                    },
                )
    finally:
        _clear_deps()

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["plaintext"].startswith("klc_pat_")
    assert body["token_prefix"] == "klc_pat_abc"
    assert body["scopes"] == ["super-admin:tenants:read"]


def test_create_pat_via_pat_auth_is_forbidden() -> None:
    _override_with(PAT_USER)
    try:
        with TestClient(app) as client:
            resp = client.post(
                "/super-admin/pats",
                json={"name": "x", "scopes": ["super-admin:tenants:read"]},
            )
    finally:
        _clear_deps()
    assert resp.status_code == 403
    assert "PAT" in resp.json()["detail"]


def test_create_pat_rejects_empty_scopes() -> None:
    _override_with(JWT_USER)
    try:
        with TestClient(app) as client:
            resp = client.post("/super-admin/pats", json={"name": "x", "scopes": []})
    finally:
        _clear_deps()
    assert resp.status_code == 422


def test_create_pat_rejects_too_many_scopes() -> None:
    _override_with(JWT_USER)
    try:
        with TestClient(app) as client:
            resp = client.post(
                "/super-admin/pats",
                json={"name": "x", "scopes": [f"scope:{i}" for i in range(25)]},
            )
    finally:
        _clear_deps()
    assert resp.status_code == 422


def test_create_pat_unauthenticated() -> None:
    with TestClient(app) as client:
        resp = client.post("/super-admin/pats", json={"name": "x", "scopes": ["x"]})
    assert resp.status_code == 401


def test_list_pats_returns_user_tokens() -> None:
    _override_with(JWT_USER)
    pats = [_make_pat(101), _make_pat(102, revoked=True)]
    try:
        with patch(
            "app.routers.super_admin.pats.list_user_pats",
            new_callable=AsyncMock,
            return_value=pats,
        ):
            with TestClient(app) as client:
                resp = client.get("/super-admin/pats")
    finally:
        _clear_deps()

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    ids = [item["id"] for item in body["items"]]
    assert ids == [101, 102]
    assert body["items"][1]["revoked_at"] is not None


def test_revoke_own_pat() -> None:
    _override_with(JWT_USER)
    pat = _make_pat(101)
    try:
        with (
            patch(
                "app.routers.super_admin.pats.list_user_pats",
                new_callable=AsyncMock,
                return_value=[pat],
            ),
            patch(
                "app.routers.super_admin.pats.revoke_pat",
                new_callable=AsyncMock,
                return_value=True,
            ),
        ):
            with TestClient(app) as client:
                resp = client.delete("/super-admin/pats/101")
    finally:
        _clear_deps()
    assert resp.status_code == 204


def test_revoke_pat_not_owned_returns_404() -> None:
    _override_with(JWT_USER)
    pat = _make_pat(999)  # user owns 999, requests revoke of 555
    try:
        with patch(
            "app.routers.super_admin.pats.list_user_pats",
            new_callable=AsyncMock,
            return_value=[pat],
        ):
            with TestClient(app) as client:
                resp = client.delete("/super-admin/pats/555")
    finally:
        _clear_deps()
    assert resp.status_code == 404


def test_revoke_already_revoked_returns_409() -> None:
    _override_with(JWT_USER)
    pat = _make_pat(101, revoked=True)
    try:
        with (
            patch(
                "app.routers.super_admin.pats.list_user_pats",
                new_callable=AsyncMock,
                return_value=[pat],
            ),
            patch(
                "app.routers.super_admin.pats.revoke_pat",
                new_callable=AsyncMock,
                return_value=False,
            ),
        ):
            with TestClient(app) as client:
                resp = client.delete("/super-admin/pats/101")
    finally:
        _clear_deps()
    assert resp.status_code == 409
