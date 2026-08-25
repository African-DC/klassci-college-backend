"""Router portail enseignant — endpoints read-only /teacher."""

from datetime import date

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import (
    TokenData,
    get_current_user,
    get_tenant_db,
    require_permission,
)
from app.schemas.attendance import ClassAttendanceStats
from app.schemas.teacher_portal import (
    TeacherClassesListResponse,
    TeacherClassRosterResponse,
    TeacherDashboardStats,
    TeacherScheduleResponse,
    TeacherUpcomingEval,
)
from app.schemas.timetable import (
    TeacherAvailabilityCreate,
    TeacherAvailabilityResponse,
    TeacherAvailabilityUpdate,
    TeacherWeekResponse,
)
from app.services import teacher_availability_service, teacher_portal_service

router = APIRouter(prefix="/teacher", tags=["teacher-portal"])


@router.get("/classes", response_model=TeacherClassesListResponse)
async def get_teacher_classes(
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_tenant_db),
) -> TeacherClassesListResponse:
    """Retourne les classes assignées à l'enseignant connecté."""
    return await teacher_portal_service.get_classes(db, current_user.user_id)


@router.get("/schedule", response_model=TeacherScheduleResponse)
async def get_teacher_schedule(
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_tenant_db),
) -> TeacherScheduleResponse:
    """Retourne l'emploi du temps personnel de l'enseignant connecté."""
    return await teacher_portal_service.get_schedule(db, current_user.user_id)


@router.get("/dashboard", response_model=TeacherDashboardStats)
async def get_teacher_dashboard(
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_tenant_db),
) -> TeacherDashboardStats:
    """Retourne le dashboard enseignant (KPIs + prochain cours + évaluations à venir)."""
    return await teacher_portal_service.get_dashboard_stats(db, current_user.user_id)


@router.get("/evaluations", response_model=list[TeacherUpcomingEval])
async def list_teacher_evaluations(
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_tenant_db),
) -> list[TeacherUpcomingEval]:
    """Liste toutes les évaluations du prof connecté pour la page Mes évaluations."""
    return await teacher_portal_service.list_evaluations(db, current_user.user_id)


@router.get("/classes/{class_id}/students", response_model=TeacherClassRosterResponse)
async def get_class_roster(
    class_id: int,
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_tenant_db),
) -> TeacherClassRosterResponse:
    """Liste des eleves inscrits d'une classe assignee a l'enseignant (pour l'appel)."""
    return await teacher_portal_service.get_class_roster(db, current_user.user_id, class_id)


@router.get("/classes/{class_id}/attendance", response_model=ClassAttendanceStats)
async def get_class_attendance(
    class_id: int,
    academic_year_id: int | None = Query(None),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_tenant_db),
) -> ClassAttendanceStats:
    """Stats de presence pour une classe assignee a l'enseignant connecte."""
    return await teacher_portal_service.get_class_attendance(
        db,
        current_user.user_id,
        class_id,
        academic_year_id=academic_year_id,
        date_from=date_from,
        date_to=date_to,
    )


# ---------------------------------------------------------------------------
# Mes disponibilites
#
# L'enseignant gere les siennes et rien d'autre : chaque ecriture repasse par
# son identifiant enseignant, jamais par celui envoye dans l'URL.
# ---------------------------------------------------------------------------


@router.get("/availabilities", response_model=list[TeacherAvailabilityResponse])
async def list_my_availabilities(
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_tenant_db),
) -> list[TeacherAvailabilityResponse]:
    """Les plages que l'enseignant connecte a declarees."""
    teacher_id = await teacher_portal_service.resolve_teacher_id(db, current_user.user_id)
    return await teacher_availability_service.list_for_teacher(db, teacher_id)


@router.get("/week", response_model=TeacherWeekResponse)
async def get_my_week(
    academic_year_id: int | None = Query(None),
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_tenant_db),
) -> TeacherWeekResponse:
    """Sa semaine occupee : ses cours et ses plages fermees, cote a cote."""
    teacher_id = await teacher_portal_service.resolve_teacher_id(db, current_user.user_id)
    return await teacher_availability_service.week_for_teacher(
        db, teacher_id, academic_year_id=academic_year_id
    )


@router.post(
    "/availabilities",
    response_model=TeacherAvailabilityResponse,
    status_code=status.HTTP_201_CREATED,
)
async def declare_my_availability(
    data: TeacherAvailabilityCreate,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("timetable:availability:self_declare"),
    db: AsyncSession = Depends(get_tenant_db),
) -> TeacherAvailabilityResponse:
    """Declare une plage sur sa propre semaine."""
    teacher_id = await teacher_portal_service.resolve_teacher_id(db, current_user.user_id)
    return await teacher_availability_service.create(db, teacher_id, data)


@router.patch("/availabilities/{av_id}", response_model=TeacherAvailabilityResponse)
async def update_my_availability(
    av_id: int,
    data: TeacherAvailabilityUpdate,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("timetable:availability:self_declare"),
    db: AsyncSession = Depends(get_tenant_db),
) -> TeacherAvailabilityResponse:
    """Rouvre ou referme une de ses plages."""
    teacher_id = await teacher_portal_service.resolve_teacher_id(db, current_user.user_id)
    return await teacher_availability_service.update(db, av_id, data, teacher_id=teacher_id)


@router.delete("/availabilities/{av_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_availability(
    av_id: int,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("timetable:availability:self_declare"),
    db: AsyncSession = Depends(get_tenant_db),
) -> None:
    """Retire une de ses plages."""
    teacher_id = await teacher_portal_service.resolve_teacher_id(db, current_user.user_id)
    await teacher_availability_service.remove(db, av_id, teacher_id=teacher_id)
