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

import asyncio
import hashlib
import ipaddress
import logging
import re
import tempfile
from dataclasses import dataclass

import jwt
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import settings
from app.core.database import current_tenant_id
from app.core.redis import get_redis_client

logger = logging.getLogger(__name__)

# Hôtes qui mappent vers le tenant de développement local
# Inclut "testserver" (par défaut FastAPI TestClient) pour ne pas casser la suite tests.
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "testserver", ""}
_PUBLIC_UPLOAD_PREFIXES = ("/public/verify-file/", "/public/verify-file-code/")
_MAX_PUBLIC_UPLOAD_BODY_BYTES = 20 * 1024 * 1024 + 256 * 1024
_PUBLIC_UPLOADS_PER_MINUTE = 8
_PUBLIC_UPLOAD_SLOTS = asyncio.Semaphore(4)
_PUBLIC_UPLOAD_MEMORY_BYTES = 1024 * 1024
_RATE_LIMIT_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return count
"""


def _trusted_client_ip(scope: Scope, request: Request) -> str:
    peer = scope.get("client")
    peer_host = str(peer[0]) if peer else "unknown"
    if peer_host in {"127.0.0.1", "::1"}:
        for header in ("x-forwarded-for", "x-real-ip"):
            forwarded = request.headers.get(header, "").strip()
            try:
                return str(ipaddress.ip_address(forwarded))
            except ValueError:
                continue
    return peer_host


async def _consume_public_upload_quota(scope: Scope, request: Request) -> JSONResponse | None:
    client_ip = _trusted_client_ip(scope, request)
    fingerprint = hashlib.sha256(client_ip.encode("utf-8")).hexdigest()[:24]
    key = f"public:document-seal-upload:{fingerprint}"
    try:
        redis = get_redis_client()
        count = await redis.eval(_RATE_LIMIT_SCRIPT, 1, key, 60)
    except Exception:
        logger.exception("Document seal upload rate limiter unavailable")
        return JSONResponse(
            status_code=503,
            content={"detail": "Vérification de fichier temporairement indisponible."},
        )
    if count > _PUBLIC_UPLOADS_PER_MINUTE:
        return JSONResponse(
            status_code=429,
            content={"detail": "Trop de vérifications. Réessayez dans une minute."},
            headers={"Retry-After": "60"},
        )
    return None


async def _spool_limited_body(
    receive: Receive,
) -> tuple[tempfile.SpooledTemporaryFile[bytes], int] | None:
    """Spool a bounded upload before Starlette's multipart parser sees it."""
    body = tempfile.SpooledTemporaryFile(max_size=_PUBLIC_UPLOAD_MEMORY_BYTES, mode="w+b")
    received_bytes = 0
    try:
        while True:
            message = await receive()
            if message["type"] != "http.request":
                break
            chunk = message.get("body", b"")
            received_bytes += len(chunk)
            if received_bytes > _MAX_PUBLIC_UPLOAD_BODY_BYTES:
                body.close()
                return None
            body.write(chunk)
            if not message.get("more_body", False):
                break
        body.seek(0)
        return body, received_bytes
    except BaseException:
        body.close()
        raise


@dataclass
class _PreparedUpload:
    receive: Receive
    body: tempfile.SpooledTemporaryFile[bytes] | None = None
    slot_acquired: bool = False

    def close(self) -> None:
        if self.body is not None:
            self.body.close()
        if self.slot_acquired:
            _PUBLIC_UPLOAD_SLOTS.release()


def _replay_spooled_body(body: tempfile.SpooledTemporaryFile[bytes], size: int) -> Receive:
    remaining = size

    async def replay() -> Message:
        nonlocal remaining
        if remaining <= 0:
            return {"type": "http.request", "body": b"", "more_body": False}
        chunk = body.read(min(1024 * 1024, remaining))
        remaining -= len(chunk)
        return {"type": "http.request", "body": chunk, "more_body": remaining > 0}

    return replay


def _file_too_large() -> JSONResponse:
    return JSONResponse(
        status_code=413,
        content={"detail": "PDF too large", "code": "FILE_TOO_LARGE"},
    )


async def _prepare_public_upload(
    scope: Scope, request: Request, receive: Receive
) -> tuple[_PreparedUpload | None, JSONResponse | None]:
    is_upload = scope["type"] == "http" and request.url.path.startswith(_PUBLIC_UPLOAD_PREFIXES)
    if not is_upload:
        return _PreparedUpload(receive), None
    content_length = request.headers.get("content-length")
    if content_length and content_length.isdigit():
        if int(content_length) > _MAX_PUBLIC_UPLOAD_BODY_BYTES:
            return None, _file_too_large()
    if quota_response := await _consume_public_upload_quota(scope, request):
        return None, quota_response

    await _PUBLIC_UPLOAD_SLOTS.acquire()
    try:
        spooled = await _spool_limited_body(receive)
    except BaseException:
        _PUBLIC_UPLOAD_SLOTS.release()
        raise
    if spooled is None:
        _PUBLIC_UPLOAD_SLOTS.release()
        return None, _file_too_large()
    body, size = spooled
    return _PreparedUpload(_replay_spooled_body(body, size), body, True), None


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


def _tenant_from_public_path(path: str) -> str | None:
    """Extrait le tenant du path des routes publiques de vérification.

    Ces routes (`/public/verify/{tenant}/...`, `/public/verify-code/{tenant}/...`,
    `/public/mailpulse/inbound/{tenant}`) n'ont pas de JWT : le tenant est porté
    par l'URL pour scoper la bonne DB.
    """
    for prefix in (
        "/public/verify/",
        "/public/verify-code/",
        "/public/verify-file/",
        "/public/verify-file-code/",
        "/public/mailpulse/inbound/",
    ):
        if path.startswith(prefix):
            seg = path[len(prefix) :].split("/", 1)[0].strip().lower()
            if seg == settings.LOCAL_TENANT_ID or _TENANT_SLUG_RE.match(seg):
                return seg
    return None


def _resolve_tenant(request: Request) -> str:
    """Résout le tenant_id selon l'ordre :
    0. Path public de vérification (/public/verify/{tenant}/...)
    1. JWT claim tenant_id (Authorization header)
    2. Header X-Tenant-Slug (login flow, avant JWT)
    3. Subdomain (rétrocompat multi-subdomain)
    4. Host local → LOCAL_TENANT_ID
    """
    if tenant := _tenant_from_public_path(request.url.path):
        return tenant

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

            prepared, error = await _prepare_public_upload(scope, request, receive)
            if error is not None:
                await error(scope, receive, send)
                return
            assert prepared is not None
            try:
                tenant = _resolve_tenant(request)
                token = current_tenant_id.set(tenant)
                try:
                    await self.app(scope, prepared.receive, send)
                finally:
                    current_tenant_id.reset(token)
            finally:
                prepared.close()
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
