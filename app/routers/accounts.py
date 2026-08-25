"""Routeur de gestion des comptes de connexion des acteurs (admin).

Consultation / création / réinitialisation du compte d'un élève, parent,
enseignant ou membre du personnel depuis sa fiche. Gardé par
`admin:accounts:manage` (admin, directeur, personnel).
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import TokenData, get_current_user, get_tenant_db, require_permission
from app.schemas.account import (
    AccountActionResponse,
    AccountCreateRequest,
    AccountStatusResponse,
)
from app.services import account_service

router = APIRouter(prefix="/admin/accounts", tags=["accounts"])

_PERM = "admin:accounts:manage"


@router.get("/{entity_type}/{entity_id}", response_model=AccountStatusResponse)
async def get_account(
    entity_type: str,
    entity_id: int,
    _: None = require_permission(_PERM),
    db: AsyncSession = Depends(get_tenant_db),
) -> AccountStatusResponse:
    """État du compte : existe ou non, email, dernière connexion, email suggéré."""
    return await account_service.get_account_status(db, entity_type, entity_id)


@router.post("/{entity_type}/{entity_id}", response_model=AccountActionResponse, status_code=201)
async def create_account(
    entity_type: str,
    entity_id: int,
    data: AccountCreateRequest,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission(_PERM),
    db: AsyncSession = Depends(get_tenant_db),
) -> AccountActionResponse:
    """Crée le compte (élève/parent) avec un mot de passe temporaire `Bonjour@AAAA`."""
    return await account_service.create_account(
        db, entity_type, entity_id, data.email, created_by=current_user.user_id
    )


@router.post("/{entity_type}/{entity_id}/reset-password", response_model=AccountActionResponse)
async def reset_password(
    entity_type: str,
    entity_id: int,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission(_PERM),
    db: AsyncSession = Depends(get_tenant_db),
) -> AccountActionResponse:
    """Réinitialise le mot de passe à `Bonjour@AAAA` (changement forcé ensuite)."""
    return await account_service.reset_password(
        db, entity_type, entity_id, reset_by=current_user.user_id
    )
