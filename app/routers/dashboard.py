"""Router dashboard — statistiques globales de l'établissement."""

from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import TokenData, get_current_user, get_tenant_db
from app.models.enrollment import Enrollment, EnrollmentStatus
from app.models.fee import EnrollmentFee, EnrollmentFeeStatus
from app.models.grade import Evaluation, Grade
from app.models.timetable import DayOfWeek, TimetableSlot

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

_DAY_MAP = {
    0: DayOfWeek.MONDAY,
    1: DayOfWeek.TUESDAY,
    2: DayOfWeek.WEDNESDAY,
    3: DayOfWeek.THURSDAY,
    4: DayOfWeek.FRIDAY,
}


class DashboardStatsResponse(BaseModel):
    enrolled_students: int
    pending_payments: int
    courses_today: int
    alerts: int


@router.get("/stats", response_model=DashboardStatsResponse)
async def get_dashboard_stats(
    _: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_tenant_db),
) -> DashboardStatsResponse:
    """Retourne les KPIs du dashboard admin en un seul round-trip DB."""
    today_weekday = date.today().weekday()
    day_enum = _DAY_MAP.get(today_weekday)

    # Subqueries — exécutées en un seul SELECT
    enrolled_sq = (
        select(func.count())
        .select_from(Enrollment)
        .where(
            Enrollment.status.in_([
                EnrollmentStatus.PROSPECT,
                EnrollmentStatus.EN_VALIDATION,
                EnrollmentStatus.VALIDE,
            ])
        )
        .correlate(None)
        .scalar_subquery()
    )
    pending_sq = (
        select(func.count())
        .select_from(EnrollmentFee)
        .where(EnrollmentFee.status == EnrollmentFeeStatus.PENDING)
        .correlate(None)
        .scalar_subquery()
    )
    courses_sq = (
        select(func.count())
        .select_from(TimetableSlot)
        .where(TimetableSlot.day == day_enum if day_enum is not None else False)
        .correlate(None)
        .scalar_subquery()
    )
    alerts_sq = (
        select(func.count())
        .select_from(Evaluation)
        .where(Evaluation.id.notin_(select(Grade.evaluation_id).distinct()))
        .correlate(None)
        .scalar_subquery()
    )

    row = (
        await db.execute(
            select(
                enrolled_sq.label("enrolled"),
                pending_sq.label("pending"),
                courses_sq.label("courses"),
                alerts_sq.label("alerts"),
            )
        )
    ).one()

    return DashboardStatsResponse(
        enrolled_students=row.enrolled or 0,
        pending_payments=row.pending or 0,
        courses_today=row.courses or 0,
        alerts=row.alerts or 0,
    )
