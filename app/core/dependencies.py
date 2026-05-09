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
        from app.services.pat_service import scope_matches

        if current_user.auth_method == "pat":
            if not scope_matches(current_user.pat_scopes, permission_slug):
                raise PermissionDeniedError(f"PAT scope missing: {permission_slug}")
            return

        from app.repositories.permission_repository import check_user_permission

        has_perm = await check_user_permission(db, current_user.user_id, permission_slug)
        if not has_perm:
            raise PermissionDeniedError(permission_slug)

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
