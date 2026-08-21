"""Router portail parent — endpoints /parent."""

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import TokenData, get_current_user, get_tenant_db, require_role
from app.routers._pdf_helpers import pdf_response
from app.schemas.parent_portal import (
    ChildBulletinsResponse,
    ChildFeesResponse,
    ChildGradesResponse,
    ChildrenListResponse,
    ChildTimetableResponse,
    ParentDashboardResponse,
)
from app.services import parent_portal_service

router = APIRouter(
    prefix="/parent",
    tags=["parent-portal"],
    dependencies=[require_role("parent", "admin", "director")],
)


@router.get("/dashboard", response_model=ParentDashboardResponse)
async def get_dashboard(
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_tenant_db),
) -> ParentDashboardResponse:
    """Dashboard parent : enfants liés avec moyenne, absences, frais restants."""
    return await parent_portal_service.get_dashboard(db, current_user.user_id)


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


@router.get("/children/{student_id}/bulletins/{bulletin_id}/pdf")
async def get_child_bulletin_pdf(
    student_id: int,
    bulletin_id: int,
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_tenant_db),
) -> Response:
    """PDF d'un bulletin publie d'un enfant du parent connecte.

    Pas de `require_permission("reports:read")` ici : ce droit ouvre les
    bulletins de toute l'ecole. La garde est le lien de filiation, verifie
    dans le service.
    """
    return await pdf_response(
        lambda: parent_portal_service.get_child_bulletin_pdf(
            db, current_user.user_id, student_id, bulletin_id
        ),
        filename=f"bulletin_{bulletin_id}.pdf",
        error_context=f"bulletin {bulletin_id}",
    )


@router.get("/children/{student_id}/timetable", response_model=ChildTimetableResponse)
async def get_child_timetable(
    student_id: int,
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_tenant_db),
) -> ChildTimetableResponse:
    """Retourne l'emploi du temps de la classe d'un enfant du parent connecté."""
    return await parent_portal_service.get_child_timetable(db, current_user.user_id, student_id)
