"""Tests du TenantMiddleware — extraction et validation du slug tenant."""

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from app.core.config import settings
from app.core.database import current_tenant_id
from app.core.middleware import TenantMiddleware, _extract_tenant


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


# ---------------------------------------------------------------------------
# TenantMiddleware.__call__ — test ASGI via httpx
# ---------------------------------------------------------------------------

async def _tenant_echo(request: Request) -> PlainTextResponse:
    """Endpoint de test : retourne le tenant_id injecté par le middleware."""
    return PlainTextResponse(current_tenant_id.get())


_test_app = TenantMiddleware(
    Starlette(routes=[Route("/tenant", _tenant_echo)])
)


@pytest.mark.asyncio
async def test_middleware_sets_tenant_from_subdomain() -> None:
    async with AsyncClient(transport=ASGITransport(app=_test_app), base_url="http://lycee-x.klassci.com") as client:
        response = await client.get("/tenant")
    assert response.status_code == 200
    assert response.text == "lycee-x"


@pytest.mark.asyncio
async def test_middleware_local_host_uses_local_tenant() -> None:
    async with AsyncClient(transport=ASGITransport(app=_test_app), base_url="http://localhost") as client:
        response = await client.get("/tenant")
    assert response.status_code == 200
    assert response.text == settings.LOCAL_TENANT_ID


@pytest.mark.asyncio
async def test_middleware_invalid_slug_falls_back_to_local() -> None:
    async with AsyncClient(transport=ASGITransport(app=_test_app), base_url="http://_bad.klassci.com") as client:
        response = await client.get("/tenant")
    assert response.status_code == 200
    assert response.text == settings.LOCAL_TENANT_ID
