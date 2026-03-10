"""Dépendances FastAPI partagées : session DB, utilisateur courant, permissions."""

from collections.abc import AsyncGenerator
from dataclasses import dataclass

import jwt
from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import current_tenant_id, get_db
from app.core.exceptions import UnauthorizedError
from app.core.security import decode_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


@dataclass
class TokenData:
    """Données extraites du JWT — représente l'utilisateur authentifié."""

    user_id: int
    tenant_id: str
    email: str


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

async def get_current_user(
    token: str = Depends(oauth2_scheme),
) -> TokenData:
    """Décode le JWT et retourne les données de l'utilisateur authentifié.

    Vérifie que le tenant_id du token correspond au tenant de la requête.
    La vérification DB complète (user actif, etc.) sera ajoutée en issue #3.
    """
    try:
        payload = decode_token(token)
    except jwt.ExpiredSignatureError:
        raise UnauthorizedError("Token has expired")
    except jwt.InvalidTokenError:
        raise UnauthorizedError("Invalid token")

    if payload.get("type") != "access":
        raise UnauthorizedError("Invalid token type")

    token_tenant = payload.get("tenant_id", "")
    request_tenant = current_tenant_id.get()
    if token_tenant != request_tenant:
        raise UnauthorizedError("Token tenant mismatch")

    return TokenData(
        user_id=int(payload["sub"]),
        tenant_id=token_tenant,
        email=payload.get("email", ""),
    )


# ---------------------------------------------------------------------------
# Permissions dynamiques
# ---------------------------------------------------------------------------

def require_permission(permission_slug: str) -> Depends:  # type: ignore[return]
    """Retourne une dépendance FastAPI qui vérifie une permission en base.

    La vérification DB réelle sera implémentée en issue #3 (table permissions).
    Pour l'instant, tout utilisateur authentifié est autorisé (stub structurel).
    """

    async def _check(
        current_user: TokenData = Depends(get_current_user),
        db: AsyncSession = Depends(get_tenant_db),
    ) -> None:
        # TODO(issue-3): vérifier la permission en base
        # has_perm = await check_user_permission(db, current_user.user_id, permission_slug)
        # if not has_perm:
        #     raise PermissionDeniedError(permission_slug)
        pass

    return Depends(_check)
