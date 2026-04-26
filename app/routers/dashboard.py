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

    # Simple query — résolution du nom en Python pour éviter les sous-requêtes corrélées
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(10)
    result = await db.execute(stmt)
    logs = result.scalars().all()

    # Résoudre les noms utilisateurs en batch
    user_ids = {log.user_id for log in logs if log.user_id}
    user_names: dict[int, str] = {}
    if user_ids:
        # Chercher dans les profils
        for Model in (StaffProfile, TeacherProfile, Student):
            found = (
                await db.execute(
                    select(Model.user_id, Model.first_name, Model.last_name).where(
                        Model.user_id.in_(user_ids)
                    )
                )
            ).all()
            for row in found:
                if row.user_id not in user_names:
                    user_names[row.user_id] = f"{row.first_name} {row.last_name}"
        # Fallback email
        missing = user_ids - set(user_names.keys())
        if missing:
            found = (
                await db.execute(select(User.id, User.email).where(User.id.in_(missing)))
            ).all()
            for row in found:
                user_names[row.id] = row.email or f"Utilisateur #{row.id}"

    items = [
        ActivityItem(
            id=log.id,
            entity_type=log.entity_type,
            action=log.action if isinstance(log.action, str) else log.action.value,
            entity_id=log.entity_id,
            user_id=log.user_id,
            user_name=user_names.get(log.user_id) if log.user_id else None,
            description=_build_description(
                log.entity_type,
                log.action if isinstance(log.action, str) else log.action.value,
            ),
            created_at=log.created_at,
        )
        for log in logs
    ]

    return ActivityResponse(items=items)
