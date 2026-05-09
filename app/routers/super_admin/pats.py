"""Personal Access Tokens — create / list / revoke (current user's tokens)."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import TokenData, get_current_user, get_tenant_db, require_permission
from app.schemas.pat import (
    PATCreateRequest,
    PATCreateResponse,
    PATListItem,
    PATListResponse,
)
from app.services.pat_service import create_pat, list_user_pats, revoke_pat

router = APIRouter(prefix="/pats", tags=["super-admin"])


@router.post(
    "",
    response_model=PATCreateResponse,
    status_code=201,
    summary="Mint a new personal access token",
)
async def issue_pat(
    data: PATCreateRequest,
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_tenant_db),
    _: None = require_permission("super-admin:pats:manage"),
) -> PATCreateResponse:
    if current_user.auth_method == "pat":
        raise HTTPException(
            status_code=403,
            detail="Cannot mint a PAT using a PAT — log in with a JWT to issue tokens.",
        )

    pat, plaintext = await create_pat(
        db,
        user_id=current_user.user_id,
        name=data.name,
        scopes=data.scopes,
        expires_in_days=data.expires_in_days,
    )
    await db.commit()

    return PATCreateResponse(
        id=pat.id,
        name=pat.name,
        token_prefix=pat.token_prefix,
        scopes=list(pat.scopes),
        expires_at=pat.expires_at,
        last_used_at=pat.last_used_at,
        revoked_at=pat.revoked_at,
        created_at=pat.created_at,
        plaintext=plaintext,
    )


@router.get(
    "",
    response_model=PATListResponse,
    summary="List the current user's personal access tokens",
)
async def list_pats(
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_tenant_db),
    _: None = require_permission("super-admin:pats:manage"),
) -> PATListResponse:
    pats = await list_user_pats(db, current_user.user_id)
    items = [PATListItem.model_validate(p) for p in pats]
    return PATListResponse(items=items, total=len(items))


@router.delete(
    "/{pat_id}",
    status_code=204,
    summary="Revoke a personal access token",
)
async def revoke_token(
    pat_id: int,
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_tenant_db),
    _: None = require_permission("super-admin:pats:manage"),
) -> None:
    pats = await list_user_pats(db, current_user.user_id)
    if not any(p.id == pat_id for p in pats):
        raise HTTPException(status_code=404, detail="PAT not found")
    revoked = await revoke_pat(db, pat_id)
    if not revoked:
        raise HTTPException(status_code=409, detail="PAT already revoked")
    await db.commit()
