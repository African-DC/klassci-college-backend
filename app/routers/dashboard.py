"""Router dashboard — statistiques globales de l'établissement."""

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi import APIRouter, Depends

from app.core.dependencies import get_current_user, get_tenant_db
from app.models.enrollment import Enrollment, EnrollmentStatus
from app.models.fee import EnrollmentFee, EnrollmentFeeStatus
from app.models.timetable import TimetableSlot, DayOfWeek
from app.models.grade import Evaluation, Grade

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

_DAY_MAP = {
    0: DayOfWeek.MONDAY,
    1: DayOfWeek.TUESDAY,
    2: DayOfWeek.WEDNESDAY,
    3: DayOfWeek.THURSDAY,
    4: DayOfWeek.FRIDAY,
}


@router.get("/stats")
async def get_dashboard_stats(
    _: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict:
    """Retourne les KPIs du dashboard admin."""
    # 1. Élèves inscrits (status valide)
    enrolled = (
        await db.execute(
            select(func.count())
            .select_from(Enrollment)
            .where(
                Enrollment.status == EnrollmentStatus.VALIDE,
            )
        )
    ).scalar() or 0

    # 2. Paiements en attente
    pending_payments = (
        await db.execute(
            select(func.count())
            .select_from(EnrollmentFee)
            .where(
                EnrollmentFee.status == EnrollmentFeeStatus.PENDING,
            )
        )
    ).scalar() or 0

    # 3. Cours du jour
    today_weekday = date.today().weekday()  # 0=Monday
    day_enum = _DAY_MAP.get(today_weekday)
    if day_enum is not None:
        courses_today = (
            await db.execute(
                select(func.count())
                .select_from(TimetableSlot)
                .where(
                    TimetableSlot.day == day_enum,
                )
            )
        ).scalar() or 0
    else:
        courses_today = 0

    # 4. Alertes (évaluations sans aucune note saisie)
    alerts = (
        await db.execute(
            select(func.count())
            .select_from(Evaluation)
            .where(
                Evaluation.id.notin_(select(Grade.evaluation_id).distinct()),
            )
        )
    ).scalar() or 0

    return {
        "enrolled_students": enrolled,
        "pending_payments": pending_payments,
        "courses_today": courses_today,
        "alerts": alerts,
    }
