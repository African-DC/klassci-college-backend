"""Tests des fonctions JWT — create, decode, expiration, token invalide."""

from datetime import timedelta

import jwt
import pytest

from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)

# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------


def test_hash_and_verify_password() -> None:
    plain = "secret-password-123"
    hashed = hash_password(plain)
    assert hashed != plain
    assert verify_password(plain, hashed)


def test_wrong_password_fails() -> None:
    hashed = hash_password("correct")
    assert not verify_password("wrong", hashed)


# ---------------------------------------------------------------------------
# Access token
# ---------------------------------------------------------------------------


def test_create_and_decode_access_token() -> None:
    token = create_access_token(user_id=42, tenant_id="lycee-x", email="alice@example.com")
    payload = decode_token(token)

    assert payload["sub"] == "42"
    assert payload["tenant_id"] == "lycee-x"
    assert payload["email"] == "alice@example.com"
    assert payload["type"] == "access"


def test_invalid_token_raises() -> None:
    with pytest.raises(jwt.InvalidTokenError):
        decode_token("not.a.valid.token")


def test_expired_token_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un token expiré lève jwt.ExpiredSignatureError.

    Le delta négatif doit dépasser le leeway de 30 secondes configuré dans
    decode_token, sinon PyJWT accepte encore le token.
    """
    import app.core.security as sec_module

    original_build = sec_module._build_token

    def expired_build(data: dict, expires_delta: timedelta) -> str:
        return original_build(data, timedelta(minutes=-5))  # -5 min > leeway 30s

    monkeypatch.setattr(sec_module, "_build_token", expired_build)
    token = create_access_token(user_id=1, tenant_id="t", email="x@x.com")

    with pytest.raises(jwt.ExpiredSignatureError):
        decode_token(token)


# ---------------------------------------------------------------------------
# Refresh token
# ---------------------------------------------------------------------------


def test_create_and_decode_refresh_token() -> None:
    token = create_refresh_token(user_id=7, tenant_id="lycee-y")
    payload = decode_token(token)

    assert payload["sub"] == "7"
    assert payload["tenant_id"] == "lycee-y"
    assert payload["type"] == "refresh"
