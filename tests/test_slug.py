"""Tenant slug validation — format and reserved-name checks.

Covers the two validation tiers:
- ``validate_tenant_slug``: format only, tolerant of the historical
  system tenant ``local``.
- ``validate_new_tenant_slug``: format + reserved, used at the API
  boundary when assigning a slug to a new tenant.
"""

import pytest

from app.core.slug import (
    RESERVED_SLUGS,
    is_reserved_tenant_slug,
    is_valid_tenant_slug,
    validate_new_tenant_slug,
    validate_tenant_slug,
)


class TestIsValidTenantSlug:
    @pytest.mark.parametrize(
        "slug",
        [
            "lycee-moderne",
            "ab",
            "ecole2026",
            "cca-2026",
            "lm",
            "a1",
            "lmab",
            "local",  # format-valid, even though reserved
            "admin",  # format-valid, even though reserved
        ],
    )
    def test_valid_format(self, slug: str) -> None:
        assert is_valid_tenant_slug(slug) is True

    @pytest.mark.parametrize(
        "slug",
        [
            "",
            "a",  # 1 char, too short
            "A",  # uppercase
            "Lycee-Moderne",
            "-foo",  # leading hyphen
            "foo-",  # trailing hyphen
            "foo_bar",  # underscore not allowed
            "foo.bar",  # dot not allowed
            "foo bar",  # space
            "a" * 64,  # > 63 chars
        ],
    )
    def test_invalid_format(self, slug: str) -> None:
        assert is_valid_tenant_slug(slug) is False


class TestIsReservedTenantSlug:
    @pytest.mark.parametrize(
        "slug",
        [
            "local",
            "admin",
            "super-admin",
            "api",
            "auth",
            "www",
            "mail",
            "login",
            "logout",
            "test",
            "dev",
            "staging",
            "prod",
            "production",
        ],
    )
    def test_reserved_returns_true(self, slug: str) -> None:
        assert is_reserved_tenant_slug(slug) is True
        assert slug in RESERVED_SLUGS

    @pytest.mark.parametrize(
        "slug",
        [
            "lycee-moderne",
            "ecole-x",
            "cca-2026",
            "lmab",
            "monlycee",
        ],
    )
    def test_non_reserved_returns_false(self, slug: str) -> None:
        assert is_reserved_tenant_slug(slug) is False


class TestValidateTenantSlug:
    """Regex-only validation — tolerant of reserved slugs (system tenant)."""

    def test_valid_returns_value(self) -> None:
        assert validate_tenant_slug("lycee-moderne") == "lycee-moderne"

    def test_reserved_slug_does_not_raise(self) -> None:
        # The system tenant ``local`` must still pass defensive boundary
        # checks during re-seeding / migration re-runs.
        assert validate_tenant_slug("local") == "local"

    def test_invalid_format_raises(self) -> None:
        with pytest.raises(ValueError, match="2-63 caractères"):
            validate_tenant_slug("-bad")


class TestValidateNewTenantSlug:
    """Strict validation — used at API boundary for new tenants."""

    def test_valid_non_reserved_returns_value(self) -> None:
        assert validate_new_tenant_slug("lycee-moderne") == "lycee-moderne"

    def test_invalid_format_raises_format_error(self) -> None:
        with pytest.raises(ValueError, match="2-63 caractères"):
            validate_new_tenant_slug("-bad")

    @pytest.mark.parametrize("slug", sorted(RESERVED_SLUGS))
    def test_reserved_slug_raises_reserved_error(self, slug: str) -> None:
        with pytest.raises(ValueError, match="réservé"):
            validate_new_tenant_slug(slug)

    def test_reserved_check_runs_after_format_check(self) -> None:
        # An invalid-format slug that happens to also be reserved should
        # fail with the format error first (defense in depth: don't leak
        # the reserved list to clients sending garbage).
        with pytest.raises(ValueError, match="2-63 caractères"):
            validate_new_tenant_slug("ADMIN")  # uppercase = format fail
