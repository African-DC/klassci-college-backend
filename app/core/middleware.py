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
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "testserver", "backend", ""}
_MAX_PUBLIC_UPLOAD_BODY_BYTES = 20 * 1024 * 1024 + 256 * 1024
_PUBLIC_UPLOADS_PER_MINUTE = 8
_PUBLIC_UPLOAD_SLOTS = asyncio.Semaphore(4)
_PUBLIC_UPLOAD_MEMORY_BYTES = 1024 * 1024
#: Les methodes qui portent un corps. Le garde ne s'arme que sur celles-la.
#:
#: Il se declenchait sur le CHEMIN seul. Le `GET` par lequel un telephone peint
#: sa page de depot consommait donc un jeton du quota par minute ET l'une des
#: quatre places d'envoi simultane, sans porter un octet. Sur une reprise —
#: ouvrir la page, envoyer, reessayer — le budget partait en trois gestes.
_METHODES_AVEC_CORPS = frozenset({"POST", "PUT", "PATCH"})
_RATE_LIMIT_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return count
"""


@dataclass(frozen=True)
class _GardeEnvoiPublic:
    """Le plafond, le quota et les mots d'un préfixe public qui reçoit un fichier.

    Une seule constante servait les deux : un plafond de corps de 20 Mo écrit
    pour un PDF de vérification, un compteur Redis unique, et des messages qui
    parlent de PDF et de vérification. Le dépôt de photo par téléphone hérite
    d'un préfixe voisin mais pas du sujet : une secrétaire dont la photo est
    trop lourde lisait « PDF too large », et son envoi consommait le budget de
    quelqu'un qui vérifie un diplôme à l'autre bout du pays.

    `compteur` est le segment de clé Redis : deux préfixes qui le partagent
    partagent leur quota, et l'affluence de l'un ferme l'autre.

    `corps_max` est le filet GROSSIER, pris avant que le corps ne soit lu ; le
    plafond exact d'une cible reste `read_capped`, plus bas. Il vaut donc la
    plus grosse cible du préfixe, pas la plus petite.
    """

    prefixe: str
    compteur: str
    par_minute: int
    corps_max: int
    trop_gros: str
    trop_souvent: str
    indisponible: str
    #: Compter par le dernier segment du chemin plutot que par l'adresse.
    #: Vrai quand ce segment est un jeton : il designe UN envoi, la ou une
    #: ecole entiere ne presente qu'une seule adresse publique.
    quota_par_chemin: bool = False


#: Les préfixes publics qui reçoivent des fichiers. Le tenant vient du chemin.
#:
#: TROISIÈME des trois listes que toute nouvelle route publique doit rejoindre.
#: Les deux autres : `_tenant_from_public_path` juste en dessous (sans quoi la
#: mauvaise base est ouverte) et `ROUTES_PUBLIQUES` dans
#: `scripts/check_permissions.py` (sans quoi l'intégration continue sort
#: « route sans garde »). En oublier une donne un échec différent à chaque fois.
_GARDES_ENVOI_PUBLIC: tuple[_GardeEnvoiPublic, ...] = (
    _GardeEnvoiPublic(
        prefixe="/public/verify-file/",
        compteur="document-seal-upload",
        par_minute=_PUBLIC_UPLOADS_PER_MINUTE,
        corps_max=_MAX_PUBLIC_UPLOAD_BODY_BYTES,
        trop_gros="PDF too large",
        trop_souvent="Trop de vérifications. Réessayez dans une minute.",
        indisponible="Vérification de fichier temporairement indisponible.",
    ),
    _GardeEnvoiPublic(
        prefixe="/public/verify-file-code/",
        compteur="document-seal-upload",
        par_minute=_PUBLIC_UPLOADS_PER_MINUTE,
        corps_max=_MAX_PUBLIC_UPLOAD_BODY_BYTES,
        trop_gros="PDF too large",
        trop_souvent="Trop de vérifications. Réessayez dans une minute.",
        indisponible="Vérification de fichier temporairement indisponible.",
    ),
    _GardeEnvoiPublic(
        prefixe="/public/upload-handoff/",
        # Compteur distinct : une journée d'inscriptions ne doit pas fermer la
        # vérification publique des diplômes, ni l'inverse.
        compteur="photo-handoff-upload",
        # Plus serré que la vérification : un dépôt ne se répète pas huit fois
        # par minute, et derrière ce préfixe il y a la photo d'un mineur.
        # Cinq par JETON, pas par adresse : le WiFi de l'école ne présente
        # qu'une IP, et compter dessus fermerait le guichet au sixième dépôt
        # d'une minute de rentrée. Cinq tentatives couvrent une 3G qui coupe.
        par_minute=5,
        quota_par_chemin=True,
        # La plus grosse cible du registre est la pièce jointe d'élève, à dix
        # mégaoctets ; la marge couvre l'enveloppe multipart.
        corps_max=10 * 1024 * 1024 + 256 * 1024,
        trop_gros="Fichier trop volumineux. Reprenez la photo.",
        trop_souvent="Trop d'envois. Réessayez dans une minute.",
        indisponible="Dépôt par téléphone temporairement indisponible.",
    ),
)


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


def trusted_client_ip(request: Request) -> str:
    """L'adresse de l'appelant, telle qu'on peut la journaliser.

    Le même primitif que le quota d'envoi public, exposé pour les routes qui
    doivent écrire une adresse dans le journal d'audit. Un dépôt de photo par
    téléphone en est une : l'opérateur qui confirme est identifié par sa
    session, mais la seule trace de qui a réellement pris la photo est
    l'adresse d'où elle est arrivée.

    L'en-tête `X-Forwarded-For` n'est cru que si le pair est la boucle locale,
    donc le reverse-proxy. Ailleurs, il est écrit par le client lui-même et
    vaut ce que vaut un champ libre.
    """
    return _trusted_client_ip(request.scope, request)


def _sujet_du_quota(scope: Scope, request: Request, garde: _GardeEnvoiPublic) -> str:
    """Sur qui compter : le dernier segment du chemin, sinon l'adresse.

    **Une école n'a qu'une adresse publique.** Les téléphones qui déposent une
    photo sont sur son WiFi — la donnée mobile se paie — ou derrière le CGNAT
    d'un opérateur : ils partagent tous la même IP. Compter par adresse ferait
    donc refuser le sixième dépôt de la minute un jour de rentrée à trois
    guichets, alors que rien d'anormal ne se passe.

    Quand le chemin porte un jeton, c'est lui le bon sujet : il désigne UN
    envoi, il expire seul, et cinq tentatives par envoi couvrent largement une
    3G qui coupe sans ouvrir la porte à autre chose.
    """
    if garde.quota_par_chemin:
        segment = scope.get("path", "").rstrip("/").rpartition("/")[2]
        if segment:
            return f"jeton:{segment}"
    return f"ip:{_trusted_client_ip(scope, request)}"


async def _consume_public_upload_quota(
    scope: Scope, request: Request, garde: _GardeEnvoiPublic
) -> JSONResponse | None:
    sujet = _sujet_du_quota(scope, request, garde)
    fingerprint = hashlib.sha256(sujet.encode("utf-8")).hexdigest()[:24]
    key = f"public:{garde.compteur}:{fingerprint}"
    try:
        redis = get_redis_client()
        count = await redis.eval(_RATE_LIMIT_SCRIPT, 1, key, 60)
    except Exception:
        logger.exception("Public upload rate limiter unavailable for %s", garde.prefixe)
        return JSONResponse(status_code=503, content={"detail": garde.indisponible})
    if count > garde.par_minute:
        return JSONResponse(
            status_code=429,
            content={"detail": garde.trop_souvent},
            headers={"Retry-After": "60"},
        )
    return None


async def _spool_limited_body(
    receive: Receive, corps_max: int
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
            if received_bytes > corps_max:
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


def _file_too_large(garde: _GardeEnvoiPublic) -> JSONResponse:
    # Le `code` reste commun aux préfixes : le client le teste, pas le message.
    # C'est le message qui change, parce que c'est lui qu'un humain lit.
    return JSONResponse(
        status_code=413,
        content={"detail": garde.trop_gros, "code": "FILE_TOO_LARGE"},
    )


def _garde_de_l_envoi(scope: Scope, path: str) -> _GardeEnvoiPublic | None:
    """Le garde qui s'applique à cette requête, ou aucun.

    La méthode compte autant que le chemin : un `GET` ne porte pas de corps, et
    n'a donc ni à consommer le quota d'envoi ni à occuper une place du sémaphore.
    """
    if scope["type"] != "http" or scope.get("method") not in _METHODES_AVEC_CORPS:
        return None
    for garde in _GARDES_ENVOI_PUBLIC:
        if path.startswith(garde.prefixe):
            return garde
    return None


async def _prepare_public_upload(
    scope: Scope, request: Request, receive: Receive
) -> tuple[_PreparedUpload | None, JSONResponse | None]:
    garde = _garde_de_l_envoi(scope, request.url.path)
    if garde is None:
        return _PreparedUpload(receive), None
    content_length = request.headers.get("content-length")
    if content_length and content_length.isdigit():
        if int(content_length) > garde.corps_max:
            return None, _file_too_large(garde)
    if quota_response := await _consume_public_upload_quota(scope, request, garde):
        return None, quota_response

    await _PUBLIC_UPLOAD_SLOTS.acquire()
    try:
        spooled = await _spool_limited_body(receive, garde.corps_max)
    except BaseException:
        _PUBLIC_UPLOAD_SLOTS.release()
        raise
    if spooled is None:
        _PUBLIC_UPLOAD_SLOTS.release()
        return None, _file_too_large(garde)
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
    """Extrait le tenant du path des routes publiques.

    Ces routes (`/public/verify/{tenant}/...`, `/public/verify-code/{tenant}/...`,
    `/public/upload-handoff/{tenant}/...`, `/public/mailpulse/inbound/{tenant}`)
    n'ont pas de JWT : le tenant est porté par l'URL pour scoper la bonne DB.

    DEUXIÈME des trois listes que toute nouvelle route publique doit rejoindre
    (cf. `_GARDES_ENVOI_PUBLIC` plus haut). L'oublier ici ne donne pas une
    erreur : cela donne un tenant de repli — l'établissement local — donc la
    MAUVAISE base ouverte, en silence.
    """
    for prefix in (
        "/public/verify/",
        "/public/verify-code/",
        "/public/verify-file/",
        "/public/verify-file-code/",
        "/public/upload-handoff/",
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
