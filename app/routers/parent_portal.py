"""Router portail parent — endpoints /parent."""

from fastapi import APIRouter, Depends, Query

from app.core.dependencies import TokenData, get_current_user, get_tenant_db
from app.schemas.parent_portal import (
    ChildBulletinsResponse,
    ChildFeesResponse,
    ChildGradesResponse,
    ChildrenListResponse,
)
from app.services import parent_portal_service

from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/parent", tags=["parent-portal"])


@router.get("/children", response_model=ChildrenListResponse)
async def list_children(
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_tenant_db),
) -> ChildrenListResponse:
    """Liste les enfants inscrits du parent connecté."""
    return await parent_portal_service.list_children(db, current_user.user_id)


@router.get("/children/{student_id}/grades", response_model=ChildGradesResponse)
async def get_child_grades(
    student_id: int,
    trimester: int | None = Query(None, ge=1, le=3),
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_tenant_db),
) -> ChildGradesResponse:
    """Retourne les notes d'un enfant du parent connecté."""
    return await parent_portal_service.get_child_grades(
        db, current_user.user_id, student_id, trimester=trimester
    )


@router.get("/children/{student_id}/fees", response_model=ChildFeesResponse)
async def get_child_fees(
    student_id: int,
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_tenant_db),
) -> ChildFeesResponse:
    """Retourne les frais d'un enfant du parent connecté."""
    return await parent_portal_service.get_child_fees(db, current_user.user_id, student_id)


@router.get("/children/{student_id}/bulletins", response_model=ChildBulletinsResponse)
async def get_child_bulletins(
    student_id: int,
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_tenant_db),
) -> ChildBulletinsResponse:
    """Retourne les bulletins publiés d'un enfant du parent connecté."""
    return await parent_portal_service.get_child_bulletins(db, current_user.user_id, student_id)
