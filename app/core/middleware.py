"""TenantMiddleware — résout le tenant depuis le sous-domaine de la requête.

Inclut une **host allowlist** qui rejette les requêtes avec un Host header
non conforme. Critique pour la sécurité multi-tenant : avec AUTH_TRUST_HOST=true
côté FE, un attacker contrôlant un sous-domaine arbitraire pourrait minter des
cookies d'auth s'il n'y a pas de validation explicite.
"""

import logging
import re

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config import settings
from app.core.database import current_tenant_id

logger = logging.getLogger(__name__)

# Hôtes qui mappent vers le tenant de développement local
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", ""}

# Slug valide : lettres minuscules, chiffres, tirets — 2 à 63 chars (RFC 1123)
_TENANT_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9\-]{0,61}[a-z0-9]$")

# Compilé une fois au démarrage depuis settings.ALLOWED_HOST_PATTERN
_ALLOWED_HOST_RE = re.compile(settings.ALLOWED_HOST_PATTERN)


def _is_host_allowed(hostname: str) -> bool:
    """Vérifie que le hostname est dans l'allowlist.

    Acceptés :
      - hostnames matchant ALLOWED_HOST_PATTERN (ex: lycee-x.college.klassci.com)
      - hostnames listés explicitement dans EXTRA_ALLOWED_HOSTS
      - hôtes locaux (localhost, 127.0.0.1, IPs numériques) — dev seulement
    """
    if hostname in _LOCAL_HOSTS:
        return True
    if hostname.replace(".", "").isdigit():
        return True
    if hostname in settings.EXTRA_ALLOWED_HOSTS:
        return True
    return bool(_ALLOWED_HOST_RE.match(hostname))


def _extract_tenant(host: str) -> str:
    """Extrait et valide le tenant_id depuis le header Host.

    Précondition : le hostname a déjà été validé via _is_host_allowed.

    Exemples :
        lycee-x.college.klassci.com  → "lycee-x"
        localhost                     → settings.LOCAL_TENANT_ID
        127.0.0.1                     → settings.LOCAL_TENANT_ID
    """
    hostname = host.split(":")[0]
    if hostname in _LOCAL_HOSTS:
        return settings.LOCAL_TENANT_ID
    if hostname.replace(".", "").isdigit():
        return settings.LOCAL_TENANT_ID
    parts = hostname.split(".")
    if len(parts) >= 3:
        slug = parts[0]
        if _TENANT_SLUG_RE.match(slug):
            return slug
    logger.warning(
        "Invalid or missing tenant slug in Host header: %s — falling back to local", host[:100]
    )
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
            hostname = host.split(":")[0]

            if not _is_host_allowed(hostname):
                logger.warning("Rejected request with disallowed Host header: %s", host[:100])
                response = JSONResponse(
                    status_code=400,
                    content={"detail": "Invalid host", "code": "HOST_NOT_ALLOWED"},
                )
                await response(scope, receive, send)
                return

            tenant = _extract_tenant(host)
            token = current_tenant_id.set(tenant)
            try:
                await self.app(scope, receive, send)
            finally:
                current_tenant_id.reset(token)
        else:
            await self.app(scope, receive, send)
