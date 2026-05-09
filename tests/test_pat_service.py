"""Unit tests for PAT generation, hashing, and scope wildcard matching.

DB-backed lookup/revoke/touch tests live in tests/services/test_pat_db.py and
require the integration test fixtures (real DB).
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from app.models.personal_access_token import PersonalAccessToken
from app.services.pat_service import (
    PAT_PREFIX,
    generate_token,
    has_scope,
    hash_token,
    is_pat_token,
)


def test_generate_token_has_correct_prefix_and_length() -> None:
    plaintext, token_hash, prefix = generate_token()
    assert plaintext.startswith(PAT_PREFIX)
    assert len(plaintext) == len(PAT_PREFIX) + 32
    assert len(token_hash) == 64
    assert prefix == plaintext[:12]


def test_generate_token_is_unique_per_call() -> None:
    samples = {generate_token()[0] for _ in range(50)}
    assert len(samples) == 50


def test_hash_token_is_deterministic() -> None:
    token = "klc_pat_" + "a" * 32
    assert hash_token(token) == hash_token(token)


def test_hash_token_changes_with_input() -> None:
    h1 = hash_token("klc_pat_" + "a" * 32)
    h2 = hash_token("klc_pat_" + "b" * 32)
    assert h1 != h2


def test_is_pat_token_recognises_prefix() -> None:
    assert is_pat_token("klc_pat_abc123")
    assert not is_pat_token("eyJhbGc...")  # JWT-shaped
    assert not is_pat_token("Bearer klc_pat_abc")  # bearer prefix not stripped
    assert not is_pat_token("")


def _make_pat(scopes: list[str]) -> PersonalAccessToken:
    return PersonalAccessToken(
        id=1,
        name="test",
        token_hash="x" * 64,
        token_prefix="klc_pat_xxx",
        user_id=1,
        scopes=scopes,
        expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=30),
    )


@pytest.mark.parametrize(
    "scopes,required,expected",
    [
        (["super-admin:tenants:read"], "super-admin:tenants:read", True),
        (["super-admin:tenants:read"], "super-admin:tenants:create", False),
        (["super-admin:*"], "super-admin:tenants:read", True),
        (["super-admin:*"], "super-admin:tenants:create", True),
        (["super-admin:tenants:*"], "super-admin:tenants:read", True),
        (["super-admin:tenants:*"], "super-admin:diagnose:read", False),
        (["*"], "super-admin:tenants:read", True),
        ([], "super-admin:tenants:read", False),
        (["admin:students:read"], "super-admin:tenants:read", False),
    ],
)
def test_has_scope_matrix(scopes: list[str], required: str, expected: bool) -> None:
    pat = _make_pat(scopes)
    assert has_scope(pat, required) is expected


def test_has_scope_uses_real_pat_object() -> None:
    """Sanity: ensure has_scope reads pat.scopes directly (regression guard)."""
    pat = MagicMock(spec=PersonalAccessToken)
    pat.scopes = ["super-admin:tenants:read"]
    assert has_scope(pat, "super-admin:tenants:read") is True
    assert has_scope(pat, "super-admin:tenants:create") is False
