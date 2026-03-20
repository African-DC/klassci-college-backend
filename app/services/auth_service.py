"""Service d'authentification — login, refresh, logout."""

import logging

import jwt
import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditAction, audit_log
from app.core.config import settings
from app.core.database import current_tenant_id
from app.core.exceptions import UnauthorizedError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_password,
)
from app.repositories.user_repository import (
    get_user_by_email,
    get_user_by_id,
    get_user_full_name,
    update_last_login,
)
from app.schemas.auth import RefreshResponse, TokenResponse, UserInToken

logger = logging.getLogger(__name__)

_REDIS_REFRESH_TTL = settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400  # secondes


def _redis_key(jti: str) -> str:
    return f"rt:{jti}"


async def login(
    db: AsyncSession,
    redis: aioredis.Redis,
    email: str,
    password: str,
    ip_address: str | None = None,
) -> tuple[TokenResponse, str]:
    """Authentifie l'utilisateur. Retourne (TokenResponse, refresh_token)."""
    user = await get_user_by_email(db, email)

    if not user or not verify_password(password, user.hashed_password):
        raise UnauthorizedError("Identifiants incorrects")

    if not user.is_active:
        raise UnauthorizedError("Compte désactivé")

    tenant = current_tenant_id.get()
    access_token = create_access_token(
        user_id=user.id,
        tenant_id=tenant,
        email=user.email,
    )
    refresh_token, jti = create_refresh_token(user_id=user.id, tenant_id=tenant)

    # Stocker le JTI dans Redis (whitelist) avec TTL
    await redis.setex(_redis_key(jti), _REDIS_REFRESH_TTL, str(user.id))

    await update_last_login(db, user.id)

    await audit_log(
        db,
        entity_type="user",
        action=AuditAction.LOGIN,
        user_id=user.id,
        entity_id=user.id,
        ip_address=ip_address,
    )

    first_name, last_name = get_user_full_name(user)

    response = TokenResponse(
        access_token=access_token,
        user=UserInToken(
            id=user.id,
            email=user.email,
            role=user.role,
            first_name=first_name,
            last_name=last_name,
        ),
    )
    return response, refresh_token


async def refresh(
    db: AsyncSession,
    redis: aioredis.Redis,
    refresh_token: str,
) -> tuple[RefreshResponse, str]:
    """Valide le refresh token, rotation. Retourne (RefreshResponse, new_refresh_token)."""
    try:
        payload = decode_token(refresh_token)
    except jwt.ExpiredSignatureError as exc:
        raise UnauthorizedError("Token de rafraîchissement invalide ou expiré") from exc
    except jwt.InvalidTokenError as exc:
        raise UnauthorizedError("Token de rafraîchissement invalide ou expiré") from exc

    if payload.get("type") != "refresh":
        raise UnauthorizedError("Token de rafraîchissement invalide ou expiré")

    if payload.get("tenant_id") != current_tenant_id.get():
        raise UnauthorizedError("Token tenant mismatch")

    jti = payload.get("jti", "")
    if not jti or not await redis.exists(_redis_key(jti)):
        raise UnauthorizedError("Token de rafraîchissement invalide ou expiré")

    try:
        user_id = int(payload["sub"])
    except (KeyError, ValueError, TypeError) as exc:
        raise UnauthorizedError("Token de rafraîchissement invalide ou expiré") from exc

    user = await get_user_by_id(db, user_id)
    if not user or not user.is_active:
        raise UnauthorizedError("Token de rafraîchissement invalide ou expiré")

    # Rotation : révoquer l'ancien JTI, émettre un nouveau
    await redis.delete(_redis_key(jti))

    tenant = payload.get("tenant_id", "")
    new_access = create_access_token(user_id=user.id, tenant_id=tenant, email=user.email)
    new_refresh, new_jti = create_refresh_token(user_id=user.id, tenant_id=tenant)
    await redis.setex(_redis_key(new_jti), _REDIS_REFRESH_TTL, str(user.id))

    return RefreshResponse(access_token=new_access), new_refresh


async def logout(
    db: AsyncSession,
    redis: aioredis.Redis,
    refresh_token: str,
    user_id: int,
    ip_address: str | None = None,
) -> None:
    """Révoque le refresh token en supprimant son JTI de Redis."""
    try:
        payload = decode_token(refresh_token)
        if payload.get("tenant_id") != current_tenant_id.get():
            raise UnauthorizedError("Token tenant mismatch")
        jti = payload.get("jti", "")
        if jti:
            await redis.delete(_redis_key(jti))
    except jwt.InvalidTokenError:
        # Token déjà expiré ou invalide — on logout quand même
        pass

    await audit_log(
        db,
        entity_type="user",
        action=AuditAction.LOGOUT,
        user_id=user_id,
        entity_id=user_id,
        ip_address=ip_address,
    )
    await db.commit()
