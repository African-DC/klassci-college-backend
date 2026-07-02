"""Service : feuilles de travail vierges d'une classe (appel + notes) en PDF.

Feuilles imprimables à remplir à la main. Réutilise la logique de chargement
des élèves inscrits (AY courante) du service liste de classe, mais sans les
métadonnées superflues (photo, genre, tel parent) : seul le trio N° / matricule
/ nom est nécessaire pour cocher la présence ou reporter les notes au stylo.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import NotFoundError
from app.models.academic import AcademicYear, Class
from app.models.enrollment import Enrollment, EnrollmentStatus
from app.services._school_settings_helper import (
    load_school_settings_for_pdf as _get_school_settings_dict,
)
from app.services.pdf import (
    generate_attendance_sheet_pdf,
    generate_grade_sheet_pdf,
)


async def _load_class(db: AsyncSession, class_id: int) -> Class:
    stmt = select(Class).where(Class.id == class_id).options(selectinload(Class.level))
    klass = (await db.execute(stmt)).scalar_one_or_none()
    if klass is None:
        raise NotFoundError("Class", class_id)
    return klass


async def _current_academic_year(db: AsyncSession) -> AcademicYear:
    stmt = select(AcademicYear).where(AcademicYear.is_current.is_(True)).limit(1)
    ay = (await db.execute(stmt)).scalar_one_or_none()
    if ay is None:
        raise NotFoundError("AcademicYear (current)", 0)
    return ay


async def _load_students(db: AsyncSession, class_id: int, academic_year_id: int) -> list[dict]:
    """Charge les élèves inscrits VALIDES de la classe (AY courante), triés par nom."""
    stmt = (
        select(Enrollment)
        .where(
            Enrollment.class_id == class_id,
            Enrollment.academic_year_id == academic_year_id,
            Enrollment.status == EnrollmentStatus.VALIDE.value,
        )
        .options(selectinload(Enrollment.student))
        .order_by(Enrollment.id.asc())
    )
    enrollments = list((await db.execute(stmt)).scalars().all())

    rows: list[dict] = []
    for e in enrollments:
        s = e.student
        if s is None:
            continue
        rows.append(
            {
                "enrollment_number": getattr(s, "enrollment_number", None) or "",
                "first_name": s.first_name,
                "last_name": s.last_name,
            }
        )
    rows.sort(key=lambda r: ((r["last_name"] or ""), (r["first_name"] or "")))
    return rows


async def _load_context(db: AsyncSession, class_id: int) -> tuple[dict, dict, list[dict]]:
    """Charge (school_settings, class_info, students) pour une feuille de classe."""
    klass = await _load_class(db, class_id)
    ay = await _current_academic_year(db)
    students = await _load_students(db, class_id, ay.id)
    class_info = {
        "class_name": klass.name,
        "level_name": getattr(klass.level, "name", "") if klass.level else "",
        "academic_year_name": ay.name,
        "effectif": len(students),
    }
    school = await _get_school_settings_dict(db)
    return school, class_info, students


async def get_attendance_sheet_pdf(db: AsyncSession, class_id: int, columns: int) -> bytes:
    """Génère la feuille d'appel vierge d'une classe (AY courante)."""
    school, class_info, students = await _load_context(db, class_id)
    return generate_attendance_sheet_pdf(school, class_info, students, columns=columns)


async def get_grade_sheet_pdf(db: AsyncSession, class_id: int, note_columns: int) -> bytes:
    """Génère la feuille de notes vierge d'une classe (AY courante)."""
    school, class_info, students = await _load_context(db, class_id)
    return generate_grade_sheet_pdf(school, class_info, students, note_columns=note_columns)
