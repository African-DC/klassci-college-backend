"""Router portail eleve — endpoints read-only /student."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import TokenData, get_current_user, get_tenant_db
from app.schemas.student_portal import (
    StudentBulletinsListResponse,
    StudentFeesResponse,
    StudentGradesListResponse,
    StudentProfileResponse,
    StudentTimetableResponse,
)
from app.services import student_portal_service

router = APIRouter(prefix="/student", tags=["student-portal"])


@router.get("/grades", response_model=StudentGradesListResponse)
async def get_grades(
    trimester: int | None = Query(None, ge=1, le=3),
    subject_id: int | None = Query(None, ge=1),
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_tenant_db),
) -> StudentGradesListResponse:
    """Notes de l'eleve connecte, filtrage optionnel par trimestre/matiere."""
    return await student_portal_service.get_grades(
        db, current_user.user_id, trimester=trimester, subject_id=subject_id
    )


@router.get("/timetable", response_model=StudentTimetableResponse)
async def get_timetable(
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_tenant_db),
) -> StudentTimetableResponse:
    """Emploi du temps de la classe de l'eleve."""
    return await student_portal_service.get_timetable(db, current_user.user_id)


@router.get("/fees", response_model=StudentFeesResponse)
async def get_fees(
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_tenant_db),
) -> StudentFeesResponse:
    """Frais et paiements de l'eleve."""
    return await student_portal_service.get_fees(db, current_user.user_id)


@router.get("/bulletins", response_model=StudentBulletinsListResponse)
async def get_bulletins(
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_tenant_db),
) -> StudentBulletinsListResponse:
    """Bulletins publies de l'eleve."""
    return await student_portal_service.get_bulletins(db, current_user.user_id)


@router.get("/profile", response_model=StudentProfileResponse)
async def get_profile(
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_tenant_db),
) -> StudentProfileResponse:
    """Profil complet de l'eleve."""
    return await student_portal_service.get_profile(db, current_user.user_id)
