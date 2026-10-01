"""Fiche de renseignements d'une inscription : ce qu'on pose à la création.

Une réinscription ne fait pas retaper au guichet ce que KLASSCI sait déjà :
le niveau et la série de l'an passé, la LV2, la discipline artistique, et la
qualité (redoublant ou non) qui s'en déduit avec certitude. Ce n'est pas une
supposition : l'élève était inscrit ici, dans tel niveau, et il revient dans
tel autre.

Un nouvel élève, sans inscription antérieure dans l'établissement, n'a que ce
que le guichet a tapé. Le reste reste vide.

Ce module garde aussi la seule règle de cohérence de la fiche : pas de LV2 en
6ème ni en 5ème.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import BusinessValidationError
from app.models.academic import AcademicYear, Class, Level
from app.models.enrollment import CLOSED_STATUSES, Enrollment, PreviousLevel
from app.schemas.enrollment_profile import EnrollmentProfileFields
from app.services.level_codes import LEVELS_WITHOUT_LV2, national_level_code

LV2_FORBIDDEN_MESSAGE = (
    "La LV2 ne s'enseigne pas en 6ème ni en 5ème : retirez-la pour un élève de cette classe."
)


@dataclass(frozen=True, slots=True)
class PriorSnapshot:
    """Ce que l'inscription précédente dit de l'élève."""

    level_code: PreviousLevel | None
    series: str | None
    lv2: str | None
    artistic_discipline: str | None


def ensure_lv2_allowed(level_name: str | None, lv2: object) -> None:
    """Refuse une LV2 sur une classe de 6ème ou de 5ème (422)."""
    if lv2 is not None and national_level_code(level_name) in LEVELS_WITHOUT_LV2:
        raise BusinessValidationError(LV2_FORBIDDEN_MESSAGE)


async def level_name_of_class(db: AsyncSession, class_id: int) -> str | None:
    """Le nom du niveau d'une classe, en une requête et sans chargement paresseux."""
    stmt = select(Level.name).join(Class, Class.level_id == Level.id).where(Class.id == class_id)
    return (await db.execute(stmt)).scalar_one_or_none()


async def prior_snapshot(
    db: AsyncSession, student_id: int, year: AcademicYear
) -> PriorSnapshot | None:
    """La dernière inscription de l'élève sur une année antérieure, s'il en a une.

    « Antérieure » se juge sur la date de début, comme dans
    `enrollment_history` : rien ne garantit que les années aient été créées
    dans l'ordre. Une inscription refusée, annulée ou à la corbeille ne compte
    pas, l'élève n'y a jamais été.
    """
    stmt = (
        select(Enrollment)
        .join(AcademicYear, AcademicYear.id == Enrollment.academic_year_id)
        .where(
            Enrollment.student_id == student_id,
            AcademicYear.start_date < year.start_date,
            Enrollment.status.not_in(CLOSED_STATUSES),
            Enrollment.archived_at.is_(None),
        )
        .options(
            selectinload(Enrollment.class_).selectinload(Class.level),
            selectinload(Enrollment.class_).selectinload(Class.series),
        )
        .order_by(AcademicYear.start_date.desc())
        .limit(1)
    )
    prior = (await db.execute(stmt)).scalar_one_or_none()
    if prior is None:
        return None
    class_ = prior.class_
    return PriorSnapshot(
        level_code=national_level_code(class_.level.name if class_.level else None),
        series=class_.series.name if class_.series else None,
        lv2=prior.lv2,
        artistic_discipline=prior.artistic_discipline,
    )


def _with_prior(
    typed: EnrollmentProfileFields, prior: PriorSnapshot | None, new_code: PreviousLevel | None
) -> dict[str, object]:
    """Ce qui est tapé l'emporte ; un champ laissé vide se remplit de l'antécédent."""
    values: dict[str, object] = {
        "previous_level": typed.previous_level,
        "previous_series": typed.previous_series,
        "is_repeater": typed.is_repeater,
        "lv2": typed.lv2,
        "artistic_discipline": typed.artistic_discipline,
    }
    if prior is None:
        return values
    repeater = None
    if prior.level_code is not None and new_code is not None:
        repeater = prior.level_code == new_code
    inherited: dict[str, object] = {
        "previous_level": prior.level_code,
        "previous_series": prior.series,
        "is_repeater": repeater,
        # Une LV2 héritée sur une classe qui n'en a pas serait refusée au
        # guichet suivant : on ne la recopie pas.
        "lv2": None if new_code in LEVELS_WITHOUT_LV2 else prior.lv2,
        "artistic_discipline": prior.artistic_discipline,
    }
    for name, value in inherited.items():
        if values[name] is None:
            values[name] = value
    return values


async def apply_initial_profile(
    db: AsyncSession,
    enrollment: Enrollment,
    typed: EnrollmentProfileFields,
    year: AcademicYear,
) -> None:
    """Pose la fiche d'une inscription qu'on vient de créer.

    Refuse d'abord une LV2 tapée sur une 6ème ou une 5ème, puis complète les
    champs laissés vides à partir de l'inscription de l'an passé.
    """
    level_name = await level_name_of_class(db, enrollment.class_id)
    ensure_lv2_allowed(level_name, typed.lv2)
    prior = await prior_snapshot(db, enrollment.student_id, year)
    for name, value in _with_prior(typed, prior, national_level_code(level_name)).items():
        setattr(enrollment, name, value)
    await db.flush()
