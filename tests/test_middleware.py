"""Tests du TenantMiddleware — extraction et validation du slug tenant."""

import pytest

from app.core.config import settings
from app.core.middleware import _extract_tenant


# ---------------------------------------------------------------------------
# _extract_tenant — hôtes locaux
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "0.0.0.0", "localhost:8000", ""])
def test_local_hosts_return_local_tenant(host: str) -> None:
    assert _extract_tenant(host) == settings.LOCAL_TENANT_ID


# ---------------------------------------------------------------------------
# _extract_tenant — sous-domaines valides
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "host, expected",
    [
        ("lycee-x.klassci.com", "lycee-x"),
        ("college-victor-hugo.klassci.com", "college-victor-hugo"),
        ("ab.klassci.com", "ab"),
        ("lycee-x.klassci.com:443", "lycee-x"),
    ],
)
def test_valid_subdomain_returns_slug(host: str, expected: str) -> None:
    assert _extract_tenant(host) == expected


# ---------------------------------------------------------------------------
# _extract_tenant — slugs invalides rejetés vers LOCAL_TENANT_ID
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "host",
    [
        # Injection via caractères spéciaux
        ("../../etc/passwd.klassci.com"),
        ("{injection}.klassci.com"),
        ("_invalid.klassci.com"),
        ("-bad.klassci.com"),
        ("bad-.klassci.com"),
        # Slug trop court (1 char)
        ("x.klassci.com"),
        # Pas assez de parties pour un sous-domaine
        ("klassci.com"),
        ("justone"),
    ],
)
def test_invalid_slug_falls_back_to_local(host: str) -> None:
    assert _extract_tenant(host) == settings.LOCAL_TENANT_ID
