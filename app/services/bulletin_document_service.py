"""Generation et scellement des documents bulletin."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.repositories import reports_repository as repo
from app.services._document_verification_helper import (
    DOCUMENT_RENDER_VERSION,
    build_verification,
    render_verification,
)
from app.services._school_settings_helper import (
    load_school_settings_for_pdf as _get_school_settings,
)
from app.services.attendance_service import get_student_attendance_summary
from app.services.pdf_service import generate_bulletin_pdf
from app.services.reports_subject_stats import (
    compute_general_stats,
    compute_subject_stats,
    enrich_subject_rows,
)


def _student_full_name(student: Any) -> str:
    return f"{student.first_name} {student.last_name}"


async def get_bulletin_pdf(db: AsyncSession, bulletin_id: int) -> bytes:
    """Generate and return the PDF bytes of a sealed bulletin."""
    bulletin = await repo.get_bulletin_by_id(db, bulletin_id)
    if bulletin is None:
        raise NotFoundError("Bulletin", bulletin_id)

    total_students = await repo.count_enrolled_students(
        db, bulletin.class_id, bulletin.academic_year_id
    )
    school = await _get_school_settings(db)

    # Statistiques de classe (rang par matiere, moyenne classe) + absences.
    class_bulletins = await repo.list_bulletins(
        db,
        class_id=bulletin.class_id,
        trimester=bulletin.trimester,
        academic_year_id=bulletin.academic_year_id,
    )
    subject_stats = compute_subject_stats(class_bulletins)
    class_stats = compute_general_stats(class_bulletins)
    subject_averages = enrich_subject_rows(bulletin, subject_stats)
    # Absences scopees au trimestre du bulletin si ses dates sont connues,
    # sinon repli sur l'annee entiere.
    trimester = await repo.get_trimester(db, bulletin.academic_year_id, bulletin.trimester)
    absences = await get_student_attendance_summary(
        db,
        bulletin.student_id,
        academic_year_id=bulletin.academic_year_id,
        start_date=trimester.start_date if trimester else None,
        end_date=trimester.end_date if trimester else None,
    )

    student_name = _student_full_name(bulletin.student) if bulletin.student else ""
    class_name = bulletin.class_.name if bulletin.class_ else ""
    academic_year_name = bulletin.academic_year.name if bulletin.academic_year else ""

    matricule = (
        (getattr(bulletin.student, "enrollment_number", None) or "") if bulletin.student else ""
    ).strip()
    issued_at = bulletin.generated_at or datetime.utcnow()
    suffix = matricule or str(bulletin.id)
    source_data = {
        "student_name": student_name,
        "class_name": class_name,
        "trimester": bulletin.trimester,
        "academic_year_name": academic_year_name,
        "average": bulletin.average,
        "rank": bulletin.rank,
        "total_students": total_students,
        "mention": bulletin.mention,
        "council_decision": bulletin.council_decision,
        "teacher_comment": bulletin.teacher_comment,
        "subject_averages": subject_averages,
        "class_stats": class_stats,
        "absences": absences,
        "generated_at": bulletin.generated_at,
        "school_settings": school,
        "template_version": DOCUMENT_RENDER_VERSION,
    }
    verification = await build_verification(
        db,
        document_type="bulletin",
        reference=f"BUL-{issued_at.year}-T{bulletin.trimester}-{suffix}",
        student_name=student_name,
        class_name=class_name,
        academic_year=academic_year_name,
        student_id=bulletin.student_id,
        issued_at=issued_at,
        source_data=source_data,
    )

    bulletin_data = {
        **source_data,
        "reference": verification["reference"],
        "verification": verification,
    }

    return await render_verification(
        db,
        verification,
        lambda: generate_bulletin_pdf(bulletin_data, school),
    )
