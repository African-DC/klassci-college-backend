"""Tests du TenantMiddleware — extraction tenant + host allowlist."""

import asyncio
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from app.core import middleware as middleware_module
from app.core.config import settings
from app.core.database import current_tenant_id
from app.core.middleware import (
    _MAX_PUBLIC_UPLOAD_BODY_BYTES,
    TenantMiddleware,
    _extract_tenant,
    _tenant_from_public_path,
    _trusted_client_ip,
    is_host_allowed,
)

# ---------------------------------------------------------------------------
# is_host_allowed — allowlist
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "host",
    [
        "localhost",
        "127.0.0.1",
        "0.0.0.0",
        "backend",
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
    assert is_host_allowed(host)


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
    assert not is_host_allowed(host)


# ---------------------------------------------------------------------------
# _extract_tenant — hôtes locaux (préconditionnés via is_host_allowed)
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


@pytest.mark.parametrize(
    "path",
    [
        "/public/verify/lycee-x/token",
        "/public/verify-code/lycee-x/SNI-AAAA",
        "/public/verify-file/lycee-x/token",
        "/public/verify-file-code/lycee-x/SNI-AAAA",
        # Le dépôt par téléphone : sans cette entrée, le tenant n'est pas lu du
        # chemin et la requête retombe sur l'établissement local — la MAUVAISE
        # base, en silence, sur une route qui écrit dans un sas.
        "/public/upload-handoff/lycee-x/jeton",
    ],
)
def test_public_document_paths_resolve_tenant(path: str) -> None:
    assert _tenant_from_public_path(path) == "lycee-x"


def test_forwarded_ip_is_only_trusted_from_local_reverse_proxy() -> None:
    proxied_scope = {
        "type": "http",
        "method": "POST",
        "path": "/",
        "headers": [(b"x-forwarded-for", b"203.0.113.8")],
        "client": ("127.0.0.1", 1234),
        "scheme": "http",
        "server": ("localhost", 80),
        "query_string": b"",
    }
    direct_scope = {**proxied_scope, "client": ("198.51.100.4", 1234)}

    assert _trusted_client_ip(proxied_scope, Request(proxied_scope)) == "203.0.113.8"
    assert _trusted_client_ip(direct_scope, Request(direct_scope)) == "198.51.100.4"


# ---------------------------------------------------------------------------
# TenantMiddleware — test ASGI via httpx
# ---------------------------------------------------------------------------


async def _tenant_echo(request: Request) -> PlainTextResponse:
    """Endpoint de test : retourne le tenant_id injecté par le middleware."""
    return PlainTextResponse(current_tenant_id.get())


async def _read_upload(request: Request) -> PlainTextResponse:
    await request.body()
    return PlainTextResponse("accepted")


_test_app = TenantMiddleware(
    Starlette(
        routes=[
            Route("/tenant", _tenant_echo),
            Route("/public/verify-file/local/token", _read_upload, methods=["POST"]),
            Route(
                "/public/upload-handoff/local/jeton",
                _read_upload,
                methods=["GET", "POST"],
            ),
        ]
    )
)


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


@pytest.mark.asyncio
async def test_middleware_rejects_oversized_public_pdf_before_body_parsing() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=_test_app), base_url="http://localhost"
    ) as client:
        response = await client.post(
            "/public/verify-file/local/token",
            headers={"Content-Length": str(_MAX_PUBLIC_UPLOAD_BODY_BYTES + 1)},
        )
    assert response.status_code == 413
    assert response.json()["code"] == "FILE_TOO_LARGE"


@pytest.mark.asyncio
async def test_le_depot_par_telephone_a_son_propre_plafond_et_ses_propres_mots() -> None:
    """Le garde du dépôt n'est pas celui de la vérification de document.

    Deux différences qui se voient en salle : le plafond n'est plus celui d'un
    PDF de vingt mégaoctets, et la personne dont la photo est trop lourde ne
    lit plus « PDF too large » sur un écran qui ne vérifie aucun PDF.
    """
    garde = next(
        g for g in middleware_module._GARDES_ENVOI_PUBLIC if g.prefixe == "/public/upload-handoff/"
    )
    assert garde.corps_max < _MAX_PUBLIC_UPLOAD_BODY_BYTES
    assert garde.compteur != "document-seal-upload"

    async with AsyncClient(
        transport=ASGITransport(app=_test_app), base_url="http://localhost"
    ) as client:
        response = await client.post(
            "/public/upload-handoff/local/jeton",
            headers={"Content-Length": str(garde.corps_max + 1)},
        )

    assert response.status_code == 413
    assert response.json()["code"] == "FILE_TOO_LARGE"
    assert "PDF" not in response.json()["detail"]


@pytest.mark.asyncio
async def test_une_lecture_ne_consomme_ni_quota_ni_place_d_envoi(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Le garde s'armait sur le CHEMIN seul, sans regarder la méthode.

    Le `GET` par lequel un téléphone peint sa page consommait donc un jeton du
    quota par minute et l'une des quatre places d'envoi simultané, sans porter
    un octet. Sur une reprise — ouvrir la page, envoyer, réessayer — le budget
    partait en trois gestes.
    """
    quota = AsyncMock(return_value=None)
    monkeypatch.setattr("app.core.middleware._consume_public_upload_quota", quota)
    epuise = asyncio.Semaphore(0)
    monkeypatch.setattr("app.core.middleware._PUBLIC_UPLOAD_SLOTS", epuise)

    async with AsyncClient(
        transport=ASGITransport(app=_test_app), base_url="http://localhost"
    ) as client:
        response = await asyncio.wait_for(
            client.get("/public/upload-handoff/local/jeton"), timeout=2
        )

    assert response.status_code == 200
    quota.assert_not_awaited()


@pytest.mark.asyncio
async def test_middleware_rejects_chunked_upload_while_streaming(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def body_chunks():
        yield b"%PDF-"
        yield b"payload-too-large"

    # Le plafond appartient au garde du préfixe, pas à une constante globale :
    # la vérification de document et le dépôt de photo par téléphone n'ont ni
    # la même taille, ni le même compteur, ni les mêmes mots.
    etroit = tuple(replace(garde, corps_max=8) for garde in middleware_module._GARDES_ENVOI_PUBLIC)
    monkeypatch.setattr("app.core.middleware._GARDES_ENVOI_PUBLIC", etroit)
    monkeypatch.setattr(
        "app.core.middleware._consume_public_upload_quota",
        AsyncMock(return_value=None),
    )
    async with AsyncClient(
        transport=ASGITransport(app=_test_app), base_url="http://localhost"
    ) as client:
        response = await client.post(
            "/public/verify-file/local/token",
            content=body_chunks(),
        )

    assert response.status_code == 413
    assert response.json()["code"] == "FILE_TOO_LARGE"


@pytest.mark.asyncio
async def test_cancelled_upload_releases_the_concurrency_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    semaphore = asyncio.Semaphore(1)
    monkeypatch.setattr("app.core.middleware._PUBLIC_UPLOAD_SLOTS", semaphore)
    monkeypatch.setattr(
        "app.core.middleware._consume_public_upload_quota",
        AsyncMock(return_value=None),
    )
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/public/verify-file/local/token",
        "raw_path": b"/public/verify-file/local/token",
        "query_string": b"",
        "headers": [(b"host", b"localhost")],
        "client": ("127.0.0.1", 1234),
        "server": ("localhost", 80),
    }

    async def cancelled_receive():
        raise asyncio.CancelledError

    async def unused_send(_message):
        raise AssertionError("No response should start after cancellation")

    with pytest.raises(asyncio.CancelledError):
        await _test_app(scope, cancelled_receive, unused_send)

    await asyncio.wait_for(semaphore.acquire(), timeout=0.1)
    semaphore.release()
