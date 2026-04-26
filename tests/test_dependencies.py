"""Tests de get_current_user — tenant mismatch, token expiré, mauvais type."""

from datetime import UTC
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.database import current_tenant_id
from app.core.dependencies import TokenData, get_current_user
from app.core.exceptions import UnauthorizedError
from app.core.security import create_access_token, create_refresh_token

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_token(tenant_id: str = "lycee-x") -> str:
    return create_access_token(user_id=1, tenant_id=tenant_id, email="user@test.com")


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_current_user_valid_token() -> None:
    from app.models.user import User

    token = _make_token("lycee-x")
    token_ctx = current_tenant_id.set("lycee-x")

    mock_user = MagicMock(spec=User)
    mock_user.id = 1
    mock_user.is_active = True
    mock_db = AsyncMock()

    try:
        with patch(
            "app.repositories.user_repository.get_user_by_id",
            new_callable=AsyncMock,
            return_value=mock_user,
        ):
            result = await get_current_user(token=token, db=mock_db)
    finally:
        current_tenant_id.reset(token_ctx)

    assert isinstance(result, TokenData)
    assert result.user_id == 1
    assert result.tenant_id == "lycee-x"
    assert result.email == "user@test.com"


# ---------------------------------------------------------------------------
# Tenant mismatch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_current_user_tenant_mismatch_raises() -> None:
    token = _make_token("lycee-x")
    token_ctx = current_tenant_id.set("autre-ecole")  # tenant différent
    try:
        with pytest.raises(UnauthorizedError, match="tenant mismatch"):
            await get_current_user(token=token)
    finally:
        current_tenant_id.reset(token_ctx)


# ---------------------------------------------------------------------------
# Token invalide / expiré
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_current_user_invalid_token_raises() -> None:
    token_ctx = current_tenant_id.set("lycee-x")
    try:
        with pytest.raises(UnauthorizedError, match="Invalid token"):
            await get_current_user(token="not.a.valid.token")
    finally:
        current_tenant_id.reset(token_ctx)


@pytest.mark.asyncio
async def test_get_current_user_refresh_token_rejected() -> None:
    """Un refresh token ne doit pas être accepté comme access token."""
    refresh, _ = create_refresh_token(user_id=1, tenant_id="lycee-x")
    token_ctx = current_tenant_id.set("lycee-x")
    try:
        with pytest.raises(UnauthorizedError, match="Invalid token type"):
            await get_current_user(token=refresh, db=AsyncMock())
    finally:
        current_tenant_id.reset(token_ctx)


# ---------------------------------------------------------------------------
# Claims manquants ou invalides → 401, pas 500
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_current_user_missing_sub_raises_401() -> None:
    """Un token sans claim 'sub' doit lever UnauthorizedError, pas KeyError."""
    from datetime import datetime, timedelta

    import jwt as pyjwt

    from app.core.config import settings

    payload = {
        "tenant_id": "lycee-x",
        "email": "user@test.com",
        "type": "access",
        "iat": datetime.now(UTC),
        "exp": datetime.now(UTC) + timedelta(minutes=15),
    }
    token = pyjwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    token_ctx = current_tenant_id.set("lycee-x")
    try:
        with pytest.raises(UnauthorizedError, match="Invalid token claims"):
            await get_current_user(token=token)
    finally:
        current_tenant_id.reset(token_ctx)


@pytest.mark.asyncio
async def test_get_current_user_non_int_sub_raises_401() -> None:
    """Un token avec sub non-entier doit lever UnauthorizedError, pas ValueError."""
    from datetime import datetime, timedelta

    import jwt as pyjwt

    from app.core.config import settings

    payload = {
        "sub": "not-an-integer",
        "tenant_id": "lycee-x",
        "email": "user@test.com",
        "type": "access",
        "iat": datetime.now(UTC),
        "exp": datetime.now(UTC) + timedelta(minutes=15),
    }
    token = pyjwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    token_ctx = current_tenant_id.set("lycee-x")
    try:
        with pytest.raises(UnauthorizedError, match="Invalid token claims"):
            await get_current_user(token=token)
    finally:
        current_tenant_id.reset(token_ctx)
