"""Fiche de renseignements : seize colonnes par élève, classe par classe.

Le comptable la remplissait à la main sur un tableur. Elle se lit ici en un
nombre fixe de requêtes, quelle que soit la taille de l'établissement : une
pour l'année, une pour les inscriptions, une par relation chargée.

Une inscription refusée, annulée ou à la corbeille n'y figure pas : l'élève
n'est pas dans la classe.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import NotFoundError
from app.models.academic import AcademicYear, Class
from app.models.enrollment import CLOSED_STATUSES, Enrollment
from app.models.user import Student
from app.schemas.class_information_sheet import (
    InformationSheetClass,
    InformationSheetResponse,
    InformationSheetRow,
    InformationSheetYear,
)
from app.services.enrollment_creation_helpers import get_current_academic_year


def _plain(value: object) -> str | None:
    """La valeur brute d'une colonne enum, que SQLAlchemy rende l'enum ou la chaîne."""
    if value is None:
        return None
    return str(getattr(value, "value", value))


async def _resolve_year(db: AsyncSession, academic_year_id: int | None) -> AcademicYear:
    if academic_year_id is None:
        return await get_current_academic_year(db)
    stmt = select(AcademicYear).where(AcademicYear.id == academic_year_id)
    year = (await db.execute(stmt)).scalar_one_or_none()
    if year is None:
        raise NotFoundError("AcademicYear", academic_year_id)
    return year


async def _load_enrollments(
    db: AsyncSession, academic_year_id: int, class_id: int | None
) -> list[Enrollment]:
    """Les inscriptions vivantes de l'année, triées comme la fiche les affiche."""
    stmt = (
        select(Enrollment)
        .join(Student, Student.id == Enrollment.student_id)
        .where(
            Enrollment.academic_year_id == academic_year_id,
            Enrollment.status.not_in(CLOSED_STATUSES),
            Enrollment.archived_at.is_(None),
        )
        .options(
            selectinload(Enrollment.student),
            selectinload(Enrollment.class_).selectinload(Class.level),
            selectinload(Enrollment.scholarship),
        )
        .order_by(Student.last_name, Student.first_name, Enrollment.id)
    )
    if class_id is not None:
        stmt = stmt.where(Enrollment.class_id == class_id)
    return list((await db.execute(stmt)).scalars().all())


def _level_name(class_: Class) -> str:
    return class_.level.name if class_.level else ""


def _row(enrollment: Enrollment) -> InformationSheetRow:
    student = enrollment.student
    scholarship = enrollment.scholarship
    return InformationSheetRow(
        enrollment_id=enrollment.id,
        matricule=student.enrollment_number,
        last_name=student.last_name,
        first_name=student.first_name,
        genre=_plain(student.genre),
        level_name=_level_name(enrollment.class_),
        birth_date=student.birth_date,
        birth_place=student.birth_place,
        nationality=student.nationality,
        assignment_status=_plain(enrollment.assignment_status),
        scholarship_kind=_plain(scholarship.kind) if scholarship else None,
        is_repeater=enrollment.is_repeater,
        lv2=_plain(enrollment.lv2),
        artistic_discipline=_plain(enrollment.artistic_discipline),
        has_photo=bool(student.photo_url),
        previous_level=_plain(enrollment.previous_level),
        previous_series=enrollment.previous_series,
    )


def _group_by_class(enrollments: list[Enrollment]) -> list[InformationSheetClass]:
    """Une entrée par classe, classes triées par niveau puis par nom."""
    classes: dict[int, Class] = {}
    rows: dict[int, list[InformationSheetRow]] = {}
    for enrollment in enrollments:
        classes.setdefault(enrollment.class_id, enrollment.class_)
        rows.setdefault(enrollment.class_id, []).append(_row(enrollment))
    ordered = sorted(
        classes.values(),
        key=lambda c: (c.level.order if c.level else 0, _level_name(c), c.name),
    )
    return [
        InformationSheetClass(id=c.id, name=c.name, level_name=_level_name(c), rows=rows[c.id])
        for c in ordered
    ]


def _year_ref(year: AcademicYear) -> InformationSheetYear:
    return InformationSheetYear(id=year.id, name=year.name)


async def school_sheet(
    db: AsyncSession, academic_year_id: int | None = None
) -> InformationSheetResponse:
    """Toutes les classes qui ont au moins un inscrit sur l'année (courante par défaut)."""
    year = await _resolve_year(db, academic_year_id)
    enrollments = await _load_enrollments(db, year.id, None)
    return InformationSheetResponse(
        academic_year=_year_ref(year), classes=_group_by_class(enrollments)
    )


async def class_sheet(
    db: AsyncSession, class_id: int, academic_year_id: int | None = None
) -> InformationSheetResponse:
    """Une seule classe, même vide : l'écran affiche alors une fiche sans ligne."""
    year = await _resolve_year(db, academic_year_id)
    stmt = select(Class).where(Class.id == class_id).options(selectinload(Class.level))
    class_ = (await db.execute(stmt)).scalar_one_or_none()
    if class_ is None:
        raise NotFoundError("Class", class_id)
    rows = [_row(e) for e in await _load_enrollments(db, year.id, class_id)]
    sheet_class = InformationSheetClass(
        id=class_.id, name=class_.name, level_name=_level_name(class_), rows=rows
    )
    return InformationSheetResponse(academic_year=_year_ref(year), classes=[sheet_class])
