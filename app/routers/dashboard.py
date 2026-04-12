"""Router dashboard — statistiques globales de l'établissement."""

from datetime import date, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.audit import AuditLog
from app.core.dependencies import TokenData, get_current_user, get_tenant_db
from app.models.enrollment import Enrollment, EnrollmentStatus
from app.models.fee import EnrollmentFee, EnrollmentFeeStatus
from app.models.grade import Evaluation, Grade
from app.models.timetable import DayOfWeek, TimetableSlot
from app.models.user import StaffProfile, Student, TeacherProfile, User

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
    enrollment_validated: int
    enrollment_prospect: int
    enrollment_pending: int


@router.get("/stats", response_model=DashboardStatsResponse)
async def get_dashboard_stats(
    _: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_tenant_db),
) -> DashboardStatsResponse:
    """Retourne les KPIs du dashboard admin en un seul round-trip DB."""
    today_weekday = date.today().weekday()
    day_enum = _DAY_MAP.get(today_weekday)

    # Subqueries — exécutées en un seul SELECT
    validated_sq = (
        select(func.count())
        .select_from(Enrollment)
        .where(Enrollment.status == EnrollmentStatus.VALIDE)
        .correlate(None)
        .scalar_subquery()
    )
    prospect_sq = (
        select(func.count())
        .select_from(Enrollment)
        .where(Enrollment.status == EnrollmentStatus.PROSPECT)
        .correlate(None)
        .scalar_subquery()
    )
    pending_enroll_sq = (
        select(func.count())
        .select_from(Enrollment)
        .where(Enrollment.status == EnrollmentStatus.EN_VALIDATION)
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
                validated_sq.label("validated"),
                prospect_sq.label("prospect"),
                pending_enroll_sq.label("pending_enroll"),
                pending_sq.label("pending"),
                courses_sq.label("courses"),
                alerts_sq.label("alerts"),
            )
        )
    ).one()

    validated = row.validated or 0
    prospect = row.prospect or 0
    pending_enroll = row.pending_enroll or 0

    return DashboardStatsResponse(
        enrolled_students=validated + prospect + pending_enroll,
        pending_payments=row.pending or 0,
        courses_today=row.courses or 0,
        alerts=row.alerts or 0,
        enrollment_validated=validated,
        enrollment_prospect=prospect,
        enrollment_pending=pending_enroll,
    )


# ---------------------------------------------------------------------------
# Activité récente
# ---------------------------------------------------------------------------

_DESCRIPTION_MAP: dict[tuple[str, str], str] = {
    ("payment", "create"): "Paiement enregistré",
    ("payment", "update"): "Paiement mis à jour",
    ("payment", "delete"): "Paiement supprimé",
    ("enrollment", "create"): "Inscription créée",
    ("enrollment", "update"): "Inscription mise à jour",
    ("enrollment", "delete"): "Inscription supprimée",
    ("student", "create"): "Élève créé",
    ("student", "update"): "Élève mis à jour",
    ("student", "delete"): "Élève supprimé",
    ("teacher", "create"): "Enseignant créé",
    ("teacher", "update"): "Enseignant mis à jour",
    ("teacher", "delete"): "Enseignant supprimé",
    ("staff", "create"): "Personnel créé",
    ("staff", "update"): "Personnel mis à jour",
    ("staff", "delete"): "Personnel supprimé",
    ("evaluation", "create"): "Évaluation créée",
    ("evaluation", "update"): "Évaluation mise à jour",
    ("evaluation", "delete"): "Évaluation supprimée",
    ("grade", "create"): "Notes saisies",
    ("grade", "update"): "Notes mises à jour",
    ("grade", "delete"): "Notes supprimées",
    ("fee_category", "create"): "Catégorie de frais créée",
    ("fee_category", "update"): "Catégorie de frais mise à jour",
    ("fee_variant", "create"): "Variante de frais créée",
    ("fee_variant", "update"): "Variante de frais mise à jour",
    ("timetable", "create"): "Emploi du temps créé",
    ("timetable", "update"): "Emploi du temps mis à jour",
    ("attendance", "create"): "Présence enregistrée",
    ("attendance", "update"): "Présence mise à jour",
    ("user", "create"): "Utilisateur créé",
    ("user", "update"): "Utilisateur mis à jour",
    ("user", "delete"): "Utilisateur supprimé",
    ("user", "login"): "Connexion",
    ("user", "logout"): "Déconnexion",
    ("bulletin", "create"): "Bulletin publié",
    ("notification", "create"): "Notification envoyée",
    ("class", "create"): "Classe créée",
    ("class", "update"): "Classe mise à jour",
    ("subject", "create"): "Matière créée",
    ("subject", "update"): "Matière mise à jour",
    ("academic_year", "create"): "Année scolaire créée",
    ("academic_year", "update"): "Année scolaire mise à jour",
}


def _build_description(entity_type: str, action: str) -> str:
    """Génère une description en français à partir du type d'entité et de l'action."""
    key = (entity_type.lower(), action.lower())
    if key in _DESCRIPTION_MAP:
        return _DESCRIPTION_MAP[key]
    # Fallback générique
    action_labels = {
        "create": "créé(e)",
        "update": "mis(e) à jour",
        "delete": "supprimé(e)",
        "login": "connecté",
        "logout": "déconnecté",
    }
    action_label = action_labels.get(action.lower(), action)
    return f"{entity_type.replace('_', ' ').capitalize()} {action_label}"


class ActivityItem(BaseModel):
    id: int
    entity_type: str
    action: str
    entity_id: int | None
    user_id: int | None
    user_name: str | None
    description: str
    created_at: datetime


class ActivityResponse(BaseModel):
    items: list[ActivityItem]


@router.get("/activity", response_model=ActivityResponse)
async def get_recent_activity(
    _: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_tenant_db),
) -> ActivityResponse:
    """Retourne les 10 dernières entrées du journal d'audit pour le widget activité."""

    # Sous-requêtes pour résoudre le nom de l'utilisateur depuis les profils
    staff_name = (
        select(func.concat(StaffProfile.first_name, " ", StaffProfile.last_name))
        .where(StaffProfile.user_id == AuditLog.user_id)
        .correlate(AuditLog)
        .scalar_subquery()
    )
    teacher_name = (
        select(func.concat(TeacherProfile.first_name, " ", TeacherProfile.last_name))
        .where(TeacherProfile.user_id == AuditLog.user_id)
        .correlate(AuditLog)
        .scalar_subquery()
    )
    student_name = (
        select(func.concat(Student.first_name, " ", Student.last_name))
        .where(Student.user_id == AuditLog.user_id)
        .correlate(AuditLog)
        .scalar_subquery()
    )
    user_email = (
        select(User.email)
        .where(User.id == AuditLog.user_id)
        .correlate(AuditLog)
        .scalar_subquery()
    )

    resolved_name = func.coalesce(staff_name, teacher_name, student_name, user_email)

    stmt = (
        select(
            AuditLog.id,
            AuditLog.entity_type,
            AuditLog.action,
            AuditLog.entity_id,
            AuditLog.user_id,
            resolved_name.label("user_name"),
            AuditLog.created_at,
        )
        .order_by(AuditLog.created_at.desc())
        .limit(10)
    )

    result = await db.execute(stmt)
    rows = result.all()

    items = [
        ActivityItem(
            id=row.id,
            entity_type=row.entity_type,
            action=row.action,
            entity_id=row.entity_id,
            user_id=row.user_id,
            user_name=row.user_name,
            description=_build_description(row.entity_type, row.action),
            created_at=row.created_at,
        )
        for row in rows
    ]

    return ActivityResponse(items=items)
