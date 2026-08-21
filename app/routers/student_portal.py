"""Router portail eleve — endpoints read-only /student."""

from datetime import date

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import TokenData, get_current_user, get_tenant_db
from app.routers._pdf_helpers import pdf_response
from app.schemas.attendance import StudentAttendanceResponse
from app.schemas.student_portal import (
    StudentBulletinsListResponse,
    StudentDashboardResponse,
    StudentFeesResponse,
    StudentGradesListResponse,
    StudentProfileResponse,
    StudentTimetableResponse,
)
from app.services import attendance_service, student_portal_service

router = APIRouter(prefix="/student", tags=["student-portal"])


@router.get("/dashboard", response_model=StudentDashboardResponse)
async def get_student_dashboard(
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_tenant_db),
) -> StudentDashboardResponse:
    """Dashboard élève : nom, classe, prochain cours, moyenne, frais, absences."""
    return await student_portal_service.get_dashboard(db, current_user.user_id)


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


@router.get("/bulletins/{bulletin_id}/pdf")
async def get_bulletin_pdf(
    bulletin_id: int,
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_tenant_db),
) -> Response:
    """PDF d'un bulletin publie de l'eleve connecte.

    Pas de `require_permission("reports:read")` ici : ce droit ouvre les
    bulletins de toute l'ecole, et un eleve n'a a lire que les siens. La garde
    est l'appartenance, verifiee dans le service.
    """
    return await pdf_response(
        lambda: student_portal_service.get_bulletin_pdf(db, current_user.user_id, bulletin_id),
        filename=f"bulletin_{bulletin_id}.pdf",
        error_context=f"bulletin {bulletin_id}",
    )


@router.get("/attendance", response_model=StudentAttendanceResponse)
async def get_attendance(
    status_filter: str | None = Query(None, alias="status"),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_tenant_db),
) -> StudentAttendanceResponse:
    """Historique de presence de l'eleve connecte."""
    student = await student_portal_service._get_student_for_user(db, current_user.user_id)
    return await attendance_service.get_student_attendance(
        db,
        student.id,
        status=status_filter,
        date_from=date_from,
        date_to=date_to,
        page=page,
        size=size,
    )


@router.get("/profile", response_model=StudentProfileResponse)
async def get_profile(
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_tenant_db),
) -> StudentProfileResponse:
    """Profil complet de l'eleve."""
    return await student_portal_service.get_profile(db, current_user.user_id)
