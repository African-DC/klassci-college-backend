"""Tests du TenantMiddleware — extraction tenant + host allowlist."""

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from app.core.config import settings
from app.core.database import current_tenant_id
from app.core.middleware import TenantMiddleware, _extract_tenant, _is_host_allowed

# ---------------------------------------------------------------------------
# _is_host_allowed — allowlist
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "host",
    [
        "localhost",
        "127.0.0.1",
        "0.0.0.0",
        "",
        # IPs numériques (dev)
        "16.58.132.68",
        "192.168.1.10",
        # Sous-domaines KLASSCI College valides
        "lycee-x.college.klassci.com",
        "college-victor-hugo.college.klassci.com",
        "ab.college.klassci.com",
    ],
)
def test_allowed_hosts(host: str) -> None:
    assert _is_host_allowed(host)


@pytest.mark.parametrize(
    "host",
    [
        # Domaine racine sans sous-domaine — pas de tenant
        "klassci.com",
        # Domaine sans .college (KLASSCIv2 Université, pas notre scope)
        "lycee-x.klassci.com",
        # Domaines arbitraires (potentielle injection)
        "evil.com",
        "klassci-college.evil.com",
        # Tentatives d'injection via caractères spéciaux
        "../../etc/passwd.college.klassci.com",
        "{injection}.college.klassci.com",
        "_invalid.college.klassci.com",
    ],
)
def test_disallowed_hosts(host: str) -> None:
    assert not _is_host_allowed(host)


# ---------------------------------------------------------------------------
# _extract_tenant — hôtes locaux (préconditionnés via _is_host_allowed)
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
        ("lycee-x.college.klassci.com", "lycee-x"),
        ("college-victor-hugo.college.klassci.com", "college-victor-hugo"),
        ("ab.college.klassci.com", "ab"),
        ("lycee-x.college.klassci.com:443", "lycee-x"),
    ],
)
def test_valid_subdomain_returns_slug(host: str, expected: str) -> None:
    assert _extract_tenant(host) == expected


# ---------------------------------------------------------------------------
# TenantMiddleware — test ASGI via httpx
# ---------------------------------------------------------------------------


async def _tenant_echo(request: Request) -> PlainTextResponse:
    """Endpoint de test : retourne le tenant_id injecté par le middleware."""
    return PlainTextResponse(current_tenant_id.get())


_test_app = TenantMiddleware(Starlette(routes=[Route("/tenant", _tenant_echo)]))


@pytest.mark.asyncio
async def test_middleware_sets_tenant_from_subdomain() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=_test_app), base_url="http://lycee-x.college.klassci.com"
    ) as client:
        response = await client.get("/tenant")
    assert response.status_code == 200
    assert response.text == "lycee-x"


@pytest.mark.asyncio
async def test_middleware_local_host_uses_local_tenant() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=_test_app), base_url="http://localhost"
    ) as client:
        response = await client.get("/tenant")
    assert response.status_code == 200
    assert response.text == settings.LOCAL_TENANT_ID


@pytest.mark.asyncio
async def test_middleware_rejects_disallowed_host() -> None:
    """Un hostname non allowlisté doit être rejeté en 400 sans atteindre l'app."""
    async with AsyncClient(
        transport=ASGITransport(app=_test_app), base_url="http://evil.com"
    ) as client:
        response = await client.get("/tenant")
    assert response.status_code == 400
    assert response.json()["code"] == "HOST_NOT_ALLOWED"


@pytest.mark.asyncio
async def test_middleware_rejects_klassciv2_university_subdomain() -> None:
    """Les sous-domaines KLASSCIv2 (Université) ne doivent pas atteindre College."""
    async with AsyncClient(
        transport=ASGITransport(app=_test_app), base_url="http://lycee-x.klassci.com"
    ) as client:
        response = await client.get("/tenant")
    assert response.status_code == 400
