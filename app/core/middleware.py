"""TenantMiddleware — résout le tenant via JWT, header X-Tenant-Slug, ou subdomain.

Architecture single-domain (depuis 2026-04-26) :

    https://college.klassci.com/...   ← un seul domaine pour tous les tenants
    Authorization: Bearer <jwt>        ← contient le claim tenant_id
    X-Tenant-Slug: lycee-x             ← pour les requêtes sans JWT (login)

Rétrocompat : si pas de JWT ni de header, fallback sur subdomain extraction
(pour les déploiements multi-subdomain encore en place).

Inclut une **host allowlist** qui rejette les requêtes avec un Host header
non conforme. Critique pour la sécurité multi-tenant : avec AUTH_TRUST_HOST=true
côté FE, un attacker contrôlant un sous-domaine arbitraire pourrait minter des
cookies d'auth s'il n'y a pas de validation explicite.
"""

import logging
import re

import jwt
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config import settings
from app.core.database import current_tenant_id

logger = logging.getLogger(__name__)

# Hôtes qui mappent vers le tenant de développement local
# Inclut "testserver" (par défaut FastAPI TestClient) pour ne pas casser la suite tests.
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "testserver", ""}

# Slug valide : lettres minuscules, chiffres, tirets — 2 à 63 chars (RFC 1123)
_TENANT_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9\-]{0,61}[a-z0-9]$")

# Hosts single-domain accepté en production (root + subdomains rétrocompat)
_PROD_HOST_RE = re.compile(
    r"^(college\.klassci\.com|[a-z0-9][a-z0-9\-]{0,61}\.college\.klassci\.com)$"
)

# Pattern legacy depuis settings (rétrocompat)
_ALLOWED_HOST_RE = re.compile(settings.ALLOWED_HOST_PATTERN)


def _is_host_allowed(hostname: str) -> bool:
    """Vérifie que le hostname est dans l'allowlist.

    Acceptés :
      - hôtes locaux (localhost, 127.0.0.1, IPs numériques) — dev seulement
      - hostnames listés explicitement dans EXTRA_ALLOWED_HOSTS
      - college.klassci.com (single-domain prod)
      - <tenant>.college.klassci.com (rétrocompat multi-subdomain)
      - hostnames matchant ALLOWED_HOST_PATTERN (legacy custom config)
    """
    if hostname in _LOCAL_HOSTS:
        return True
    if hostname.replace(".", "").isdigit():
        return True
    if hostname in settings.EXTRA_ALLOWED_HOSTS:
        return True
    if _PROD_HOST_RE.match(hostname):
        return True
    return bool(_ALLOWED_HOST_RE.match(hostname))


def _tenant_from_jwt(authorization: str) -> str | None:
    """Extrait tenant_id du claim JWT si l'Authorization header est valide.

    Ne valide PAS l'expiration ni la signature ici — c'est le job des dependencies.
    On a juste besoin du tenant pour scoper la DB. Si le JWT est invalide/expiré,
    le code en aval renverra 401 mais on aura déjà la bonne DB.

    Si le bearer token est un PAT (`klc_pat_*`), on retourne None : le tenant
    sera résolu via header / subdomain / fallback local. Le PAT lui-même est
    validé en DB par get_current_user (ne peut pas faire d'await ici).
    """
    from app.services.pat_service import is_pat_token

    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    token = authorization[7:].strip()
    if not token:
        return None
    if is_pat_token(token):
        return None
    try:
        # options: ne pas vérifier la signature/exp ici — juste lire le claim
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
            options={"verify_signature": True, "verify_exp": False},
        )
    except jwt.InvalidTokenError:
        return None
    tenant = payload.get("tenant_id")
    if isinstance(tenant, str) and (tenant in _LOCAL_HOSTS or _TENANT_SLUG_RE.match(tenant)):
        return tenant
    return None


def _tenant_from_header(value: str) -> str | None:
    """Valide et retourne tenant_slug depuis le header X-Tenant-Slug."""
    if not value:
        return None
    value = value.strip().lower()
    if value == settings.LOCAL_TENANT_ID or _TENANT_SLUG_RE.match(value):
        return value
    return None


def _tenant_from_subdomain(hostname: str) -> str | None:
    """Rétrocompat : extrait le tenant du sous-domaine (legacy multi-subdomain).

    college.klassci.com           → None (pas de subdomain, c'est le root)
    lycee-x.college.klassci.com   → "lycee-x"
    localhost                     → None (handled separately)
    """
    if hostname in _LOCAL_HOSTS:
        return None
    if hostname.replace(".", "").isdigit():
        return None
    parts = hostname.split(".")
    # college.klassci.com a 3 parts mais on veut SKIP : pas de tenant subdomain
    if len(parts) >= 4 or (len(parts) == 3 and not hostname.startswith("college.")):
        slug = parts[0]
        if _TENANT_SLUG_RE.match(slug):
            return slug
    return None


def _resolve_tenant(request: Request) -> str:
    """Résout le tenant_id selon l'ordre :
    1. JWT claim tenant_id (Authorization header)
    2. Header X-Tenant-Slug (login flow, avant JWT)
    3. Subdomain (rétrocompat multi-subdomain)
    4. Host local → LOCAL_TENANT_ID
    """
    auth_header = request.headers.get("authorization", "")
    if tenant := _tenant_from_jwt(auth_header):
        return tenant

    tenant_header = request.headers.get("x-tenant-slug", "")
    if tenant := _tenant_from_header(tenant_header):
        return tenant

    hostname = request.headers.get("host", "").split(":")[0]
    if tenant := _tenant_from_subdomain(hostname):
        return tenant

    if hostname in _LOCAL_HOSTS or hostname.replace(".", "").isdigit():
        return settings.LOCAL_TENANT_ID

    # college.klassci.com root sans JWT ni header → local par défaut
    # (situation transition pendant déploiement single-domain)
    return settings.LOCAL_TENANT_ID


class TenantMiddleware:
    """Middleware ASGI pur — évite le double-wrapping de BaseHTTPMiddleware."""

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

            tenant = _resolve_tenant(request)
            token = current_tenant_id.set(tenant)
            try:
                await self.app(scope, receive, send)
            finally:
                current_tenant_id.reset(token)
        else:
            await self.app(scope, receive, send)


# Backward-compat exports (used by tests)
def _extract_tenant(host: str) -> str:
    """Legacy fonction : retourne le tenant from host. Use _resolve_tenant pour la prod."""
    hostname = host.split(":")[0]
    if hostname in _LOCAL_HOSTS:
        return settings.LOCAL_TENANT_ID
    if hostname.replace(".", "").isdigit():
        return settings.LOCAL_TENANT_ID
    if tenant := _tenant_from_subdomain(hostname):
        return tenant
    return settings.LOCAL_TENANT_ID
