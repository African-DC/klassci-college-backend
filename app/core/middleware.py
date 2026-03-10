"""TenantMiddleware — résout le tenant depuis le sous-domaine de la requête."""

import re

from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config import settings
from app.core.database import current_tenant_id

# Hôtes qui mappent vers le tenant de développement local
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", ""}

# Slug valide : lettres minuscules, chiffres, tirets — 2 à 63 chars (RFC 1123)
_TENANT_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9\-]{1,61}[a-z0-9]$")


def _extract_tenant(host: str) -> str:
    """Extrait et valide le tenant_id depuis le header Host.

    Exemples :
        lycee-x.klassci.com  → "lycee-x"
        localhost             → settings.LOCAL_TENANT_ID
        127.0.0.1            → settings.LOCAL_TENANT_ID

    Un slug invalide (injection, format inconnu) est rejeté vers LOCAL_TENANT_ID.
    """
    hostname = host.split(":")[0]
    if hostname in _LOCAL_HOSTS:
        return settings.LOCAL_TENANT_ID
    parts = hostname.split(".")
    if len(parts) >= 3:
        slug = parts[0]
        if _TENANT_SLUG_RE.match(slug):
            return slug
    return settings.LOCAL_TENANT_ID


class TenantMiddleware:
    """Middleware ASGI pur — évite le double-wrapping de BaseHTTPMiddleware.

    BaseHTTPMiddleware buffer le corps complet de la réponse en mémoire et
    interdit le streaming. Ce middleware ASGI natif n'a pas ces limitations.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in {"http", "websocket"}:
            request = Request(scope)
            host = request.headers.get("host", "")
            tenant = _extract_tenant(host)
            token = current_tenant_id.set(tenant)
            try:
                await self.app(scope, receive, send)
            finally:
                current_tenant_id.reset(token)
        else:
            await self.app(scope, receive, send)
