"""Service : composition + génération de la liste de classe (PDF)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import NotFoundError
from app.models.academic import AcademicYear, Class
from app.models.enrollment import Enrollment, EnrollmentStatus
from app.models.user import ParentStudent
from app.services.pdf import generate_class_roster_pdf


from app.services._school_settings_helper import (
    load_school_settings_for_pdf as _get_school_settings_dict,
)


async def _load_class_with_room(db: AsyncSession, class_id: int) -> Class:
    stmt = (
        select(Class)
        .where(Class.id == class_id)
        .options(
            selectinload(Class.level),
            selectinload(Class.room),
        )
    )
    result = await db.execute(stmt)
    klass = result.scalar_one_or_none()
    if klass is None:
        raise NotFoundError("Class", class_id)
    return klass


async def _current_academic_year(db: AsyncSession) -> AcademicYear | None:
    stmt = select(AcademicYear).where(AcademicYear.is_current.is_(True)).limit(1)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def _load_students(
    db: AsyncSession, class_id: int, academic_year_id: int
) -> list[dict]:
    """Charge les étudiants inscrits VALIDES dans la classe pour l'AY courante."""
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
    result = await db.execute(stmt)
    enrollments = list(result.scalars().all())

    # Pour chaque étudiant, récupérer le tel parent urgence (1er parent lié)
    student_ids = [e.student_id for e in enrollments if e.student]
    parent_phone_by_student: dict[int, str] = {}
    if student_ids:
        ps_stmt = (
            select(ParentStudent)
            .where(ParentStudent.student_id.in_(student_ids))
            .options(selectinload(ParentStudent.parent))
            .order_by(ParentStudent.student_id, ParentStudent.parent_id)
        )
        ps_rows = (await db.execute(ps_stmt)).scalars().all()
        for ps in ps_rows:
            sid = ps.student_id
            if sid not in parent_phone_by_student and ps.parent and ps.parent.phone:
                parent_phone_by_student[sid] = ps.parent.phone

    rows: list[dict] = []
    for e in enrollments:
        s = e.student
        if s is None:
            continue
        initials = f"{(s.first_name or '?')[:1]}{(s.last_name or '?')[:1]}".upper()
        rows.append(
            {
                "enrollment_number": getattr(e, "enrollment_number", None) or "",
                "first_name": s.first_name,
                "last_name": s.last_name,
                "genre": getattr(s, "genre", None),
                "birth_date": getattr(s, "birth_date", None),
                "initials": initials,
                "photo_url": getattr(s, "photo_url", None),
                "parent_phone": parent_phone_by_student.get(s.id),
            }
        )

    # Tri par nom de famille puis prénom
    rows.sort(key=lambda r: ((r["last_name"] or ""), (r["first_name"] or "")))
    return rows


async def get_class_roster_pdf(db: AsyncSession, class_id: int) -> bytes:
    """Génère le PDF liste de classe pour une classe (AY courante)."""
    klass = await _load_class_with_room(db, class_id)
    ay = await _current_academic_year(db)
    if ay is None:
        raise NotFoundError("AcademicYear (current)", 0)

    students = await _load_students(db, class_id, ay.id)
    boys = sum(1 for s in students if s.get("genre") == "M")
    girls = sum(1 for s in students if s.get("genre") == "F")

    data = {
        "class_name": klass.name,
        "level_name": getattr(klass.level, "name", "") if klass.level else "",
        "academic_year_name": ay.name,
        "main_teacher_name": None,  # TODO : Class.main_teacher_id si ajouté plus tard
        "room_name": getattr(klass.room, "name", None) if klass.room else None,
        "students": students,
        "counts": {"total": len(students), "boys": boys, "girls": girls},
        "issued_at": datetime.utcnow(),
    }
    school = await _get_school_settings_dict(db)
    return generate_class_roster_pdf(data, school)
