"""Quelle inscription fait foi pour une famille : une seule règle, deux écritures.

L'année en cours d'abord, puis la dernière année déjà commencée, puis l'année
à venir. Une réinscription est plus récente sans être encore en vigueur : elle
ne remplace ni la classe ni les frais de l'année que l'élève est en train de vivre.
"""

from datetime import date

from sqlalchemy import ColumnElement, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.interfaces import LoaderOption

from app.models.academic import AcademicYear
from app.models.enrollment import Enrollment, EnrollmentStatus


def in_force_order() -> tuple[ColumnElement, ...]:
    """Le tri SQL, à poser sur une requête jointe à `AcademicYear`."""
    return (
        AcademicYear.is_current.desc(),
        (AcademicYear.start_date <= date.today()).desc(),
        AcademicYear.start_date.desc(),
        Enrollment.id.desc(),
    )


def in_force_key(enrollment: Enrollment) -> tuple[bool, bool, date, int]:
    """Le même tri, pour des inscriptions déjà chargées avec leur année."""
    year = enrollment.academic_year
    return (year.is_current, year.start_date <= date.today(), year.start_date, enrollment.id)


async def get_enrollment_in_force(
    db: AsyncSession, student_id: int, *loads: LoaderOption
) -> Enrollment | None:
    """L'inscription ouverte qui fait foi pour cet élève, avec les relations demandées."""
    stmt = (
        select(Enrollment)
        .join(Enrollment.academic_year)
        .where(
            Enrollment.student_id == student_id,
            Enrollment.status.not_in([EnrollmentStatus.ANNULE, EnrollmentStatus.REJETE]),
        )
        .options(*loads)
        .order_by(*in_force_order())
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()
