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

from app.core.audit import AuditAction, audit_log
from app.core.exceptions import BusinessValidationError
from app.models.academic import AcademicYear, Class, Level
from app.models.enrollment import CLOSED_STATUSES, Enrollment, PreviousLevel
from app.schemas.enrollment_profile import PROFILE_FIELDS, EnrollmentProfileFields
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


async def _immediately_preceding_year_id(db: AsyncSession, year: AcademicYear) -> int | None:
    """L'année qui précède directement celle-ci : la plus récente commencée avant elle."""
    stmt = (
        select(AcademicYear.id)
        .where(AcademicYear.start_date < year.start_date)
        .order_by(AcademicYear.start_date.desc())
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def prior_snapshot(
    db: AsyncSession, student_id: int, year: AcademicYear
) -> PriorSnapshot | None:
    """L'inscription de l'élève sur l'année qui précède DIRECTEMENT, s'il en a une.

    Pas « la dernière inscription connue » : un élève revenu après une année
    passée ailleurs n'était pas, l'an dernier, dans la classe qu'il avait il y
    a deux ans. Le niveau antérieur et la qualité seraient alors faux. Sans
    inscription l'année d'avant, on n'hérite de rien.

    « Précède » se juge sur la date de début, comme dans `enrollment_history` :
    rien ne garantit que les années aient été créées dans l'ordre. Une
    inscription refusée, annulée ou à la corbeille ne compte pas.
    """
    previous_year_id = await _immediately_preceding_year_id(db, year)
    if previous_year_id is None:
        return None
    stmt = (
        select(Enrollment)
        .where(
            Enrollment.student_id == student_id,
            Enrollment.academic_year_id == previous_year_id,
            Enrollment.status.not_in(CLOSED_STATUSES),
            Enrollment.archived_at.is_(None),
        )
        .options(
            selectinload(Enrollment.class_).selectinload(Class.level),
            selectinload(Enrollment.class_).selectinload(Class.series),
        )
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
    """Ce qui est tapé l'emporte ; un champ laissé vide se remplit de l'antécédent.

    Trois règles, dans cet ordre :

    - la série ne s'hérite qu'avec le niveau : une série de l'an passé collée
      à un niveau tapé autrement décrirait une classe qui n'a pas existé ;
    - la qualité se calcule sur le niveau antérieur FINAL, tapé ou hérité,
      et seulement si le guichet ne l'a pas tapée elle-même ;
    - une LV2 héritée sur une classe qui n'en a pas serait refusée au guichet
      suivant : on ne la recopie pas.
    """
    values: dict[str, object] = {
        "previous_level": typed.previous_level,
        "previous_series": typed.previous_series,
        "is_repeater": typed.is_repeater,
        "lv2": typed.lv2,
        "artistic_discipline": typed.artistic_discipline,
    }
    if prior is not None:
        if typed.previous_level is None and prior.level_code is not None:
            values["previous_level"] = prior.level_code
            if typed.previous_series is None:
                values["previous_series"] = prior.series
        if typed.lv2 is None and new_code not in LEVELS_WITHOUT_LV2:
            values["lv2"] = prior.lv2
        if typed.artistic_discipline is None:
            values["artistic_discipline"] = prior.artistic_discipline
    final_level = values["previous_level"]
    if typed.is_repeater is None and final_level is not None and new_code is not None:
        values["is_repeater"] = final_level == new_code
    return values


async def apply_initial_profile(
    db: AsyncSession,
    enrollment: Enrollment,
    typed: EnrollmentProfileFields,
    year: AcademicYear,
) -> None:
    """Pose la fiche d'une inscription qu'on vient de créer.

    Refuse d'abord une LV2 tapée sur une 6ème ou une 5ème, puis complète les
    champs laissés vides à partir de l'inscription de l'année précédente.
    """
    level_name = await level_name_of_class(db, enrollment.class_id)
    ensure_lv2_allowed(level_name, typed.lv2)
    prior = await prior_snapshot(db, enrollment.student_id, year)
    for name, value in _with_prior(typed, prior, national_level_code(level_name)).items():
        setattr(enrollment, name, value)
    await db.flush()


def profile_values(enrollment: Enrollment) -> dict[str, object]:
    """La fiche telle qu'enregistrée, en valeurs simples pour le journal JSON."""
    return {
        name: getattr(getattr(enrollment, name), "value", getattr(enrollment, name))
        for name in PROFILE_FIELDS
    }


async def clear_lv2_if_class_forbids_it(
    db: AsyncSession, enrollment: Enrollment, *, actor: int
) -> None:
    """Après un changement de classe : une LV2 n'a pas cours en 6ème ni en 5ème.

    Même règle qu'à la création, appliquée sans refuser le changement de
    classe : c'est la classe qui décide, la LV2 suit. Le retrait est journalisé.
    """
    if enrollment.lv2 is None:
        return
    code = national_level_code(await level_name_of_class(db, enrollment.class_id))
    if code not in LEVELS_WITHOUT_LV2:
        return
    old = getattr(enrollment.lv2, "value", enrollment.lv2)
    enrollment.lv2 = None
    await db.flush()
    await audit_log(
        db,
        entity_type="enrollment",
        action=AuditAction.UPDATE,
        user_id=actor,
        entity_id=enrollment.id,
        old_values={"lv2": old},
        new_values={"lv2": None},
        notes="LV2 retirée : la nouvelle classe ne l'enseigne pas.",
    )
