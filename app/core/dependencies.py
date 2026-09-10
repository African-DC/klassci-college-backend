"""Dépendances FastAPI partagées : session DB, utilisateur courant, permissions."""

import logging
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import jwt
from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import Actor, current_actor
from app.core.database import current_tenant_id, get_db
from app.core.exceptions import PermissionDeniedError, UnauthorizedError
from app.core.security import decode_token

logger = logging.getLogger(__name__)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


@dataclass
class TokenData:
    """Données extraites du JWT ou du PAT — représente l'appelant authentifié."""

    user_id: int
    tenant_id: str
    email: str
    auth_method: str = "jwt"
    pat_id: int | None = None
    pat_scopes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Session DB tenant-scopée
# ---------------------------------------------------------------------------


async def get_tenant_db() -> AsyncGenerator[AsyncSession, None]:
    """Alias explicite de get_db — session scopée sur le tenant courant.

    Délègue intégralement à get_db afin que FastAPI gère le cycle de vie
    de la session (yield → cleanup) de façon déterministe.
    """
    async for session in get_db():
        yield session


# ---------------------------------------------------------------------------
# Utilisateur courant
# ---------------------------------------------------------------------------


def _role_value(role: object) -> str:
    """Le slug du role, jamais son repr Python.

    `User.role` est une colonne Enum : `str()` y renvoie « UserRoleEnum.ADMIN »,
    qui ne correspond a rien cote interface et casse la traduction des libelles.
    """
    return str(getattr(role, "value", role))


async def _authenticate_jwt(token: str, db: AsyncSession) -> TokenData:
    try:
        payload = decode_token(token)
    except jwt.ExpiredSignatureError as exc:
        raise UnauthorizedError("Token has expired") from exc
    except jwt.InvalidTokenError as exc:
        raise UnauthorizedError("Invalid token") from exc

    if payload.get("type") != "access":
        raise UnauthorizedError("Invalid token type")

    token_tenant = payload.get("tenant_id", "")
    request_tenant = current_tenant_id.get()
    if token_tenant != request_tenant:
        raise UnauthorizedError("Token tenant mismatch")

    try:
        user_id = int(payload["sub"])
    except (KeyError, ValueError, TypeError) as exc:
        raise UnauthorizedError("Invalid token claims") from exc

    from app.repositories.user_repository import get_user_by_id

    user = await get_user_by_id(db, user_id)
    if not user or not user.is_active:
        raise UnauthorizedError("User not found or inactive")

    # L'identite est deja chargee ici : on la pose pour que chaque ecriture
    # d'audit de la requete la fige, sans requete supplementaire ni parametre
    # a ajouter aux quelque cent appels existants.
    current_actor.set(Actor(user_id=user_id, email=user.email, role=_role_value(user.role)))

    return TokenData(
        user_id=user_id,
        tenant_id=token_tenant,
        email=payload.get("email", ""),
        auth_method="jwt",
    )


_LAST_USED_THROTTLE = timedelta(minutes=5)


async def _authenticate_pat(token: str, db: AsyncSession) -> TokenData:
    from app.core.datetimes import utcnow_naive
    from app.repositories.user_repository import get_user_by_id
    from app.services.pat_service import lookup_pat, touch_last_used

    pat = await lookup_pat(db, token)
    if pat is None:
        raise UnauthorizedError("Invalid or expired access token")

    user = await get_user_by_id(db, pat.user_id)
    if not user or not user.is_active:
        raise UnauthorizedError("User not found or inactive")

    if pat.last_used_at is None or utcnow_naive() - pat.last_used_at >= _LAST_USED_THROTTLE:
        await touch_last_used(db, pat.id)

    current_actor.set(Actor(user_id=pat.user_id, email=user.email, role=_role_value(user.role)))

    return TokenData(
        user_id=pat.user_id,
        tenant_id=current_tenant_id.get(),
        email=user.email,
        auth_method="pat",
        pat_id=pat.id,
        pat_scopes=list(pat.scopes),
    )


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_tenant_db),
) -> TokenData:
    """Authenticate via JWT or PAT. Dispatch on token prefix."""
    from app.services.pat_service import is_pat_token

    if is_pat_token(token):
        return await _authenticate_pat(token, db)
    return await _authenticate_jwt(token, db)


# ---------------------------------------------------------------------------
# Permissions dynamiques
# ---------------------------------------------------------------------------


def require_permission(permission_slug: str) -> Any:
    """Retourne une dépendance FastAPI qui vérifie une permission.

    Pour les PAT : la permission doit être couverte par le scope déclaré à
    la création du token.

    Pour les JWT : lecture de la matrice rôle/permission en DB.
    """

    async def _check(
        current_user: TokenData = Depends(get_current_user),
        db: AsyncSession = Depends(get_tenant_db),
    ) -> None:
        # Une seule lecture de la matrice, partagée avec `has_permission` :
        # dupliquer la résolution des droits est exactement là où l'on ne veut
        # aucune divergence possible.
        if not await resolve_permission(current_user, db, permission_slug):
            if current_user.auth_method == "pat":
                raise PermissionDeniedError(f"PAT scope missing: {permission_slug}")
            raise PermissionDeniedError(permission_slug)

    return Depends(_check)


async def resolve_permission(
    current_user: TokenData, db: AsyncSession, permission_slug: str
) -> bool:
    """Répond à « cet appelant a-t-il ce droit ? », sans décider quoi en faire.

    Pour un PAT, la réponse vient du scope déclaré à la création du token ;
    pour un JWT, de la matrice rôle/permission en base.

    C'est le seul primitif de ce module qui prenne son slug À L'APPEL. Tout ce
    qui l'entoure — `require_permission`, `require_any_permission`,
    `has_permission` — sont des fabriques de dépendances FastAPI : elles fixent
    leur slug à la déclaration de la route, ce qui suffit tant que la route
    connaît le droit qu'elle exige.

    Certains gestes ne le connaissent qu'à l'exécution. Ouvrir une session de
    dépôt par téléphone en est un : le droit demandé dépend de ce qu'on
    photographie — un élève, un enseignant, le logo de l'établissement — et vit
    dans le registre des cibles, pas dans la signature de la route. Ces
    appelants passent par ici, jamais par une comparaison de rôle.
    """
    if current_user.auth_method == "pat":
        from app.services.pat_service import scope_matches

        return bool(scope_matches(current_user.pat_scopes, permission_slug))

    from app.repositories.permission_repository import check_user_permission

    return bool(await check_user_permission(db, current_user.user_id, permission_slug))


def require_any_permission(*permission_slugs: str) -> Any:
    """Dépendance qui laisse passer qui détient AU MOINS UN de ces droits.

    Certains gestes appartiennent légitimement à deux métiers. Régénérer les
    frais d'une inscription en est un : la comptabilité le déclenche depuis la
    fiche élève, le secrétariat depuis le dossier d'inscription, et n'accepter
    que le slug de l'autre condamne l'un des deux à réclamer de l'aide pour un
    bouton de sa propre page.

    Bâtie sur `resolve_permission`, comme `require_permission` : une seconde
    lecture de la matrice des droits finirait par répondre autre chose que la
    première, et plus personne ne saurait laquelle fait foi.
    """
    if not permission_slugs:
        raise ValueError("require_any_permission attend au moins une permission")

    async def _check(
        current_user: TokenData = Depends(get_current_user),
        db: AsyncSession = Depends(get_tenant_db),
    ) -> None:
        for slug in permission_slugs:
            if await resolve_permission(current_user, db, slug):
                return
        # Le message nomme TOUTES les permissions acceptées. N'en citer qu'une
        # enverrait un PAT réclamer un scope qu'on ne lui accordera peut-être
        # jamais, alors que l'autre lui était ouvert.
        manquantes = " ou ".join(permission_slugs)
        if current_user.auth_method == "pat":
            raise PermissionDeniedError(f"PAT scope missing: {manquantes}")
        raise PermissionDeniedError(manquantes)

    return Depends(_check)


def has_permission(permission_slug: str) -> Any:
    """Dépendance qui répond `True`/`False` au lieu de lever un 403.

    Pour les endpoints dont la permission ne décide pas de l'accès mais de
    l'ÉTENDUE : un caissier et un comptable ouvrent tous deux le journal des
    versements, mais le premier ne doit y lire que sa propre caisse. Écrire
    `if role == "cashier"` serait une permission en dur (cf. `rules/security`) ;
    on interroge donc la matrice, comme partout ailleurs.
    """

    async def _check(
        current_user: TokenData = Depends(get_current_user),
        db: AsyncSession = Depends(get_tenant_db),
    ) -> bool:
        return await resolve_permission(current_user, db, permission_slug)

    return Depends(_check)


def require_role(*role_names: str) -> Any:
    """Retourne une dépendance FastAPI qui vérifie que l'utilisateur a un des rôles donnés."""

    async def _check(
        current_user: TokenData = Depends(get_current_user),
        db: AsyncSession = Depends(get_tenant_db),
    ) -> None:
        from sqlalchemy import select

        from app.models.permission import Role, UserRole
        from app.models.user import User

        # Check the User.role enum field (fast path)
        user = await db.get(User, current_user.user_id)
        if user and user.role and user.role.value in role_names:
            return

        # Fallback: check user_roles table
        stmt = (
            select(Role.name)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == current_user.user_id, Role.name.in_(role_names))
            .limit(1)
        )
        row = (await db.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise PermissionDeniedError(f"Rôle requis : {', '.join(role_names)}")

    return Depends(_check)
