"""Service : composition + génération de la fiche d'inscription (PDF)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import NotFoundError
from app.models.academic import Class
from app.models.enrollment import Enrollment
from app.models.fee import EnrollmentFee, FeeVariant
from app.models.user import ParentStudent
from app.services._school_settings_helper import (
    load_school_settings_for_pdf as _get_school_settings_dict,
)
from app.services.pdf import generate_enrollment_form_pdf
from app.services.pdf._helpers import enum_value

_RELATIONSHIP_LABELS = {
    "father": "Père",
    "mother": "Mère",
    "guardian": "Tuteur",
    "other": "Autre",
}


async def _load_enrollment_context(db: AsyncSession, enrollment_id: int) -> Enrollment:
    """Charge l'inscription avec tout ce qu'il faut pour la fiche."""
    stmt = (
        select(Enrollment)
        .where(Enrollment.id == enrollment_id)
        .options(
            selectinload(Enrollment.student),
            selectinload(Enrollment.class_).selectinload(Class.level),
            selectinload(Enrollment.academic_year),
            selectinload(Enrollment.enrollment_fees)
            .selectinload(EnrollmentFee.fee_variant)
            .selectinload(FeeVariant.category),
        )
    )
    result = await db.execute(stmt)
    enrollment = result.scalar_one_or_none()
    if enrollment is None:
        raise NotFoundError("Enrollment", enrollment_id)
    return enrollment


async def _load_parents(db: AsyncSession, student_id: int) -> list[dict]:
    """Charge les parents liés à un élève avec leur type de relation."""
    stmt = (
        select(ParentStudent)
        .where(ParentStudent.student_id == student_id)
        .options(selectinload(ParentStudent.parent))
        .order_by(ParentStudent.parent_id.asc())
    )
    result = await db.execute(stmt)
    rows = list(result.scalars().all())

    parents: list[dict] = []
    for ps in rows:
        if ps.parent is None:
            continue
        relation_raw = (ps.relationship_type or "").lower()
        parents.append(
            {
                "first_name": ps.parent.first_name,
                "last_name": ps.parent.last_name,
                "phone": ps.parent.phone,
                "email": ps.parent.email,
                "relationship_label": _RELATIONSHIP_LABELS.get(relation_raw, relation_raw or "—"),
            }
        )
    return parents


def _student_dict(enrollment: Enrollment) -> dict:
    s = enrollment.student
    if s is None:
        return {}
    return {
        "first_name": s.first_name,
        "last_name": s.last_name,
        "genre": getattr(s, "genre", None),
        "birth_date": getattr(s, "birth_date", None),
        "birth_place": getattr(s, "birth_place", None),
        "photo_url": getattr(s, "photo_url", None),
        "city": getattr(s, "city", None),
        "commune": getattr(s, "commune", None),
        "address": getattr(s, "address", None),
    }


def _fees_dict(enrollment: Enrollment) -> list[dict]:
    """Liste des frais de l'inscription triés par priorité catégorie."""
    fees = list(enrollment.enrollment_fees or [])
    fees.sort(
        key=lambda f: (
            f.fee_variant.category.priority if f.fee_variant and f.fee_variant.category else 100,
            f.id,
        )
    )
    rows: list[dict] = []
    for f in fees:
        cat = f.fee_variant.category if f.fee_variant else None
        rows.append(
            {
                "category_name": cat.name if cat else "",
                "amount": f.amount,
                "is_mandatory": cat.is_mandatory if cat else True,
            }
        )
    return rows


async def get_enrollment_form_pdf(db: AsyncSession, enrollment_id: int) -> bytes:
    """Génère la fiche d'inscription en PDF."""
    enrollment = await _load_enrollment_context(db, enrollment_id)
    parents = await _load_parents(db, enrollment.student.id) if enrollment.student else []

    klass = enrollment.class_
    ay = enrollment.academic_year

    data = {
        "enrollment_id": enrollment.id,
        "enrollment_number": getattr(enrollment, "enrollment_number", None),
        "status": enum_value(enrollment.status),
        "student": _student_dict(enrollment),
        "class_name": getattr(klass, "name", "") if klass else "",
        "level_name": (getattr(klass.level, "name", "") if klass and klass.level else ""),
        "academic_year_name": getattr(ay, "name", "") if ay else "",
        "parents": parents,
        "fees": _fees_dict(enrollment),
        "issued_at": datetime.utcnow(),
    }
    school = await _get_school_settings_dict(db)
    return generate_enrollment_form_pdf(data, school)
