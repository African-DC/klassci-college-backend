"""Router d'authentification — login, refresh, logout, profil connecté."""

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import TokenData, get_current_user, get_tenant_db
from app.core.redis import get_redis
from app.repositories.user_repository import get_user_by_id, get_user_full_name
from app.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    RefreshResponse,
    TokenResponse,
    UserMeResponse,
)
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


def _client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


@router.post("/login", response_model=TokenResponse)
async def login(
    data: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
    redis: aioredis.Redis = Depends(get_redis),
) -> TokenResponse:
    """Authentifie l'utilisateur et retourne access_token + refresh_token."""
    return await auth_service.login(
        db=db,
        redis=redis,
        email=data.email,
        password=data.password,
        ip_address=_client_ip(request),
    )


@router.post("/refresh", response_model=RefreshResponse)
async def refresh(
    data: RefreshRequest,
    db: AsyncSession = Depends(get_tenant_db),
    redis: aioredis.Redis = Depends(get_redis),
) -> RefreshResponse:
    """Émet un nouvel access_token à partir d'un refresh_token valide."""
    return await auth_service.refresh(db=db, redis=redis, refresh_token=data.refresh_token)


@router.post("/logout", status_code=204)
async def logout(
    data: RefreshRequest,
    request: Request,
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_tenant_db),
    redis: aioredis.Redis = Depends(get_redis),
) -> None:
    """Révoque le refresh token et logue l'action."""
    await auth_service.logout(
        db=db,
        redis=redis,
        refresh_token=data.refresh_token,
        user_id=current_user.user_id,
        ip_address=_client_ip(request),
    )


@router.get("/me", response_model=UserMeResponse)
async def me(
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_tenant_db),
) -> UserMeResponse:
    """Retourne le profil de l'utilisateur authentifié."""
    from app.core.exceptions import NotFoundError

    user = await get_user_by_id(db, current_user.user_id)
    if not user:
        raise NotFoundError("User", current_user.user_id)

    first_name, last_name = get_user_full_name(user)

    return UserMeResponse(
        id=user.id,
        email=user.email,
        role=user.role,
        first_name=first_name,
        last_name=last_name,
        tenant_id=current_user.tenant_id,
        is_active=user.is_active,
    )
