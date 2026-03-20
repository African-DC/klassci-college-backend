"""Tests des endpoints d'authentification."""

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from app.core.dependencies import TokenData, get_current_user, get_tenant_db
from app.core.redis import get_redis
from app.main import app
from app.schemas.auth import RefreshResponse, TokenResponse, UserInToken

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_USER = UserInToken(
    id=1,
    email="admin@college.ci",
    role="admin",
    first_name="Jean",
    last_name="Koné",
)

VALID_TOKEN_RESPONSE = TokenResponse(
    access_token="access.token.here",
    user=VALID_USER,
)

VALID_REFRESH_RESPONSE = RefreshResponse(
    access_token="new.access.token",
)


# ---------------------------------------------------------------------------
# POST /auth/login
# ---------------------------------------------------------------------------


def test_login_success() -> None:
    """Login OK → 200 + access_token + refresh_token en cookie httpOnly."""
    with patch(
        "app.routers.auth.auth_service.login",
        new_callable=AsyncMock,
        return_value=(VALID_TOKEN_RESPONSE, "refresh.token.here"),
    ):
        with TestClient(app) as client:
            resp = client.post(
                "/auth/login",
                json={"email": "admin@college.ci", "password": "secret"},
            )
    assert resp.status_code == 200
    body = resp.json()
    assert body["access_token"] == "access.token.here"
    assert body["token_type"] == "bearer"
    assert body["user"]["email"] == "admin@college.ci"
    assert body["user"]["role"] == "admin"
    # refresh_token NE doit PAS apparaître dans le body
    assert "refresh_token" not in body
    # refresh_token doit être posé en cookie httpOnly
    assert "refresh_token" in resp.cookies


def test_login_wrong_password() -> None:
    """Mauvais mot de passe → 401."""
    from app.core.exceptions import UnauthorizedError

    with patch(
        "app.routers.auth.auth_service.login",
        new_callable=AsyncMock,
        side_effect=UnauthorizedError("Identifiants incorrects"),
    ):
        with TestClient(app) as client:
            resp = client.post(
                "/auth/login",
                json={"email": "admin@college.ci", "password": "wrong"},
            )
    assert resp.status_code == 401
    assert "Identifiants incorrects" in resp.json()["detail"]


def test_login_invalid_email_format() -> None:
    """Email invalide → 422 (Pydantic validation)."""
    with TestClient(app) as client:
        resp = client.post(
            "/auth/login",
            json={"email": "not-an-email", "password": "secret"},
        )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /auth/refresh
# ---------------------------------------------------------------------------


def test_refresh_success() -> None:
    """Refresh OK via cookie → 200 + nouveau access_token."""
    with patch(
        "app.routers.auth.auth_service.refresh",
        new_callable=AsyncMock,
        return_value=(VALID_REFRESH_RESPONSE, "new.refresh.token"),
    ):
        with TestClient(app) as client:
            # Le refresh_token est envoyé via cookie httpOnly
            client.cookies.set("refresh_token", "valid.refresh.token")
            resp = client.post("/auth/refresh")
    assert resp.status_code == 200
    body = resp.json()
    assert body["access_token"] == "new.access.token"
    assert "refresh_token" not in body


def test_refresh_invalid_token() -> None:
    """Token de refresh invalide → 401."""
    from app.core.exceptions import UnauthorizedError

    with patch(
        "app.routers.auth.auth_service.refresh",
        new_callable=AsyncMock,
        side_effect=UnauthorizedError("Token de rafraîchissement invalide ou expiré"),
    ):
        with TestClient(app) as client:
            client.cookies.set("refresh_token", "expired.token")
            resp = client.post("/auth/refresh")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /auth/logout
# ---------------------------------------------------------------------------


def test_logout_success() -> None:
    """Logout avec cookie de refresh valide → 204."""
    mock_token_data = TokenData(user_id=1, tenant_id="local", email="admin@college.ci")

    app.dependency_overrides[get_current_user] = lambda: mock_token_data
    app.dependency_overrides[get_tenant_db] = lambda: AsyncMock()
    app.dependency_overrides[get_redis] = lambda: AsyncMock()
    try:
        with patch(
            "app.routers.auth.auth_service.logout",
            new_callable=AsyncMock,
            return_value=None,
        ):
            with TestClient(app) as client:
                # Le refresh_token est envoyé via cookie httpOnly
                client.cookies.set("refresh_token", "valid.refresh.token")
                resp = client.post(
                    "/auth/logout",
                    headers={"Authorization": "Bearer valid.access.token"},
                )
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 204


# ---------------------------------------------------------------------------
# GET /auth/me
# ---------------------------------------------------------------------------


def test_me_returns_user_profile() -> None:
    """GET /auth/me → profil complet de l'utilisateur."""
    from app.models.user import User

    mock_token_data = TokenData(user_id=1, tenant_id="lycee-x", email="admin@college.ci")

    mock_user = MagicMock(spec=User)
    mock_user.id = 1
    mock_user.email = "admin@college.ci"
    mock_user.role = "admin"
    mock_user.is_active = True
    mock_user.staff_profile = MagicMock(first_name="Jean", last_name="Koné")
    mock_user.teacher_profile = None
    mock_user.student_profile = None
    mock_user.parent_profile = None

    app.dependency_overrides[get_current_user] = lambda: mock_token_data
    app.dependency_overrides[get_tenant_db] = lambda: AsyncMock()
    app.dependency_overrides[get_redis] = lambda: AsyncMock()
    try:
        with patch(
            "app.routers.auth.get_user_by_id",
            new_callable=AsyncMock,
            return_value=mock_user,
        ):
            with TestClient(app) as client:
                resp = client.get("/auth/me")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == 1
    assert body["email"] == "admin@college.ci"
    assert body["tenant_id"] == "lycee-x"
    assert body["first_name"] == "Jean"
    assert body["last_name"] == "Koné"


def test_me_unauthenticated() -> None:
    """Pas de token → 401."""
    with TestClient(app) as client:
        resp = client.get("/auth/me")
    assert resp.status_code == 401
