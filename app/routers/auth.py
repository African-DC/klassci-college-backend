"""Router d'authentification — login, refresh, logout, profil connecté."""

import redis.asyncio as aioredis
from fastapi import APIRouter, Cookie, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.dependencies import TokenData, get_current_user, get_tenant_db
from app.core.exceptions import UnauthorizedError
from app.core.redis import get_redis
from app.repositories.user_repository import get_user_by_id, get_user_full_name
from app.schemas.auth import (
    LoginRequest,
    RefreshResponse,
    TokenResponse,
    UserMeResponse,
)
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])

_COOKIE_NAME = "refresh_token"
_COOKIE_MAX_AGE = settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400


def _client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=_COOKIE_NAME,
        value=token,
        httponly=True,
        max_age=_COOKIE_MAX_AGE,
        path="/",
        samesite="lax",
        secure=settings.APP_ENV != "development",
    )


@router.post("/login", response_model=TokenResponse)
async def login(
    data: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_tenant_db),
    redis: aioredis.Redis = Depends(get_redis),
) -> TokenResponse:
    """Authentifie l'utilisateur. Refresh token posé en httpOnly cookie."""
    token_response, refresh_token = await auth_service.login(
        db=db,
        redis=redis,
        email=data.email,
        password=data.password,
        ip_address=_client_ip(request),
    )
    _set_refresh_cookie(response, refresh_token)
    return token_response


@router.post("/refresh", response_model=RefreshResponse)
async def refresh(
    response: Response,
    db: AsyncSession = Depends(get_tenant_db),
    redis: aioredis.Redis = Depends(get_redis),
    refresh_token: str | None = Cookie(default=None, alias=_COOKIE_NAME),
) -> RefreshResponse:
    """Émet un nouvel access_token depuis le cookie refresh_token."""
    if not refresh_token:
        raise UnauthorizedError("Refresh token manquant")
    refresh_response, new_refresh = await auth_service.refresh(
        db=db, redis=redis, refresh_token=refresh_token
    )
    _set_refresh_cookie(response, new_refresh)
    return refresh_response


@router.post("/logout", status_code=204)
async def logout(
    request: Request,
    response: Response,
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_tenant_db),
    redis: aioredis.Redis = Depends(get_redis),
    refresh_token: str | None = Cookie(default=None, alias=_COOKIE_NAME),
) -> None:
    """Révoque le refresh token et efface le cookie."""
    if refresh_token:
        await auth_service.logout(
            db=db,
            redis=redis,
            refresh_token=refresh_token,
            user_id=current_user.user_id,
            ip_address=_client_ip(request),
        )
    response.delete_cookie(key=_COOKIE_NAME)


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
