"""Service conseil de classe — generation du PV et decisions."""

import logging
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditAction, audit_log
from app.core.exceptions import BusinessValidationError, NotFoundError
from app.models.academic import SchoolSettings
from app.repositories import council_repository as repo
from app.schemas.council import (
    CouncilMinutesGenerateRequest,
    CouncilMinutesResponse,
    CouncilMinutesPdfResponse,
    CouncilStudentDecisionResponse,
    DecisionOverrideRequest,
)
from app.services.pdf_service import generate_council_minutes_pdf

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Decision thresholds
# ---------------------------------------------------------------------------


def get_auto_decision(average: Decimal | None) -> str:
    """Determine la decision automatique selon la moyenne."""
    if average is None:
        return "exclusion"
    if average >= 10:
        return "passage"
    if average >= Decimal("9.5"):
        return "repechage"
    if average >= Decimal("8.5"):
        return "redoublement"
    return "exclusion"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _student_name(student: object) -> str:
    return f"{student.first_name} {student.last_name}"  # type: ignore[attr-defined]


def _build_decision_response(d: object) -> CouncilStudentDecisionResponse:
    return CouncilStudentDecisionResponse(
        id=d.id,  # type: ignore[attr-defined]
        student_id=d.student_id,  # type: ignore[attr-defined]
        student_name=_student_name(d.student) if d.student else "",  # type: ignore[attr-defined]
        average=d.average,  # type: ignore[attr-defined]
        rank=d.rank,  # type: ignore[attr-defined]
        absence_count=d.absence_count,  # type: ignore[attr-defined]
        auto_decision=d.auto_decision,  # type: ignore[attr-defined]
        final_decision=d.final_decision,  # type: ignore[attr-defined]
        override_reason=d.override_reason,  # type: ignore[attr-defined]
    )


def _build_response(council: object) -> CouncilMinutesResponse:
    return CouncilMinutesResponse(
        id=council.id,  # type: ignore[attr-defined]
        class_id=council.class_id,  # type: ignore[attr-defined]
        class_name=council.class_.name if council.class_ else "",  # type: ignore[attr-defined]
        academic_year_id=council.academic_year_id,  # type: ignore[attr-defined]
        trimester=council.trimester,  # type: ignore[attr-defined]
        main_teacher_name=council.main_teacher_name,  # type: ignore[attr-defined]
        director_name=council.director_name,  # type: ignore[attr-defined]
        dren_name=council.dren_name,  # type: ignore[attr-defined]
        notes=council.notes,  # type: ignore[attr-defined]
        generated_at=council.generated_at,  # type: ignore[attr-defined]
        is_published=council.is_published,  # type: ignore[attr-defined]
        decisions=[_build_decision_response(d) for d in council.decisions],  # type: ignore[attr-defined]
        created_at=council.created_at,  # type: ignore[attr-defined]
        updated_at=council.updated_at,  # type: ignore[attr-defined]
    )


# ---------------------------------------------------------------------------
# Generate
# ---------------------------------------------------------------------------


async def generate_council_minutes(
    db: AsyncSession,
    data: CouncilMinutesGenerateRequest,
    generated_by: int,
) -> CouncilMinutesResponse:
    """Genere le PV du conseil de classe pour une classe/trimestre."""
    # Check if already exists — delete old one to regenerate
    existing = await repo.get_council_minutes(
        db, data.class_id, data.trimester, data.academic_year_id
    )
    if existing is not None:
        async with db.begin_nested():
            await repo.delete_council_minutes(db, existing)

    # Get enrolled students
    students = await repo.get_enrolled_students(db, data.class_id, data.academic_year_id)
    if not students:
        raise BusinessValidationError(
            f"No enrolled students found for class {data.class_id}"
        )

    async with db.begin_nested():
        # Create the council minutes record
        council = await repo.create_council_minutes(
            db,
            class_id=data.class_id,
            academic_year_id=data.academic_year_id,
            trimester=data.trimester,
            main_teacher_name=data.main_teacher_name,
            director_name=data.director_name,
            dren_name=data.dren_name,
            notes=data.notes,
        )

        # Collect bulletin data for all students
        for student in students:
            bulletin = await repo.get_bulletin_for_student(
                db, student.id, data.class_id, data.academic_year_id, data.trimester
            )
            absence_count = await repo.count_absences_for_student(
                db, student.id, data.class_id, data.academic_year_id
            )
            average = bulletin.average if bulletin else None
            rank = bulletin.rank if bulletin else None
            auto_decision = get_auto_decision(average)

            await repo.create_student_decision(
                db,
                council_minutes_id=council.id,
                student_id=student.id,
                average=average,
                rank=rank,
                absence_count=absence_count,
                auto_decision=auto_decision,
            )

        await audit_log(
            db,
            entity_type="council_minutes",
            action=AuditAction.CREATE,
            user_id=generated_by,
            entity_id=council.id,
            new_values={
                "class_id": data.class_id,
                "trimester": data.trimester,
                "academic_year_id": data.academic_year_id,
            },
        )

    await db.commit()

    # Reload with relations
    refreshed = await repo.get_council_minutes_by_id(db, council.id)
    if refreshed is None:
        raise NotFoundError("CouncilMinutes", council.id)
    return _build_response(refreshed)


# ---------------------------------------------------------------------------
# Get
# ---------------------------------------------------------------------------


async def get_council_minutes(
    db: AsyncSession,
    class_id: int,
    trimester: int,
    academic_year_id: int,
) -> CouncilMinutesResponse:
    """Retourne le PV du conseil ou 404."""
    council = await repo.get_council_minutes(db, class_id, trimester, academic_year_id)
    if council is None:
        raise NotFoundError(
            "CouncilMinutes",
            f"class={class_id}/trimester={trimester}",
        )
    return _build_response(council)


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------


async def _get_school_settings(db: AsyncSession) -> dict:
    """Fetch the singleton SchoolSettings row."""
    stmt = select(SchoolSettings).limit(1)
    result = await db.execute(stmt)
    settings = result.scalar_one_or_none()
    if settings is None:
        return {"school_name": "Etablissement", "ministry_code": None}
    return {
        "school_name": settings.school_name,
        "ministry_code": settings.ministry_code,
        "address": settings.address,
        "phone": settings.phone,
    }


async def get_council_minutes_pdf(
    db: AsyncSession,
    class_id: int,
    trimester: int,
    academic_year_id: int,
) -> bytes:
    """Generate and return the PDF bytes of the council minutes."""
    council = await repo.get_council_minutes(db, class_id, trimester, academic_year_id)
    if council is None:
        raise NotFoundError(
            "CouncilMinutes",
            f"class={class_id}/trimester={trimester}",
        )

    school = await _get_school_settings(db)

    decisions = [
        {
            "student_name": _student_name(d.student) if d.student else "",
            "average": d.average,
            "rank": d.rank,
            "absence_count": d.absence_count,
            "auto_decision": d.auto_decision,
            "final_decision": d.final_decision,
            "override_reason": d.override_reason,
        }
        for d in (council.decisions or [])
    ]

    council_data = {
        "class_name": council.class_.name if council.class_ else "",
        "trimester": council.trimester,
        "academic_year_name": council.academic_year.name if council.academic_year else "",
        "main_teacher_name": council.main_teacher_name,
        "director_name": council.director_name,
        "dren_name": council.dren_name,
        "notes": council.notes,
        "generated_at": council.generated_at,
        "decisions": decisions,
    }

    return generate_council_minutes_pdf(council_data, school)

# ---------------------------------------------------------------------------
# Override decision
# ---------------------------------------------------------------------------


async def override_decision(
    db: AsyncSession,
    decision_id: int,
    data: DecisionOverrideRequest,
    overridden_by: int,
) -> CouncilStudentDecisionResponse:
    """Override la decision automatique pour un eleve."""
    decision = await repo.get_decision_by_id(db, decision_id)
    if decision is None:
        raise NotFoundError("CouncilStudentDecision", decision_id)

    old_values = {
        "final_decision": decision.final_decision,
        "override_reason": decision.override_reason,
    }

    async with db.begin_nested():
        await repo.update_decision_override(
            db, decision, data.final_decision, data.override_reason
        )
        await audit_log(
            db,
            entity_type="council_student_decision",
            action=AuditAction.UPDATE,
            user_id=overridden_by,
            entity_id=decision_id,
            old_values=old_values,
            new_values={
                "final_decision": data.final_decision,
                "override_reason": data.override_reason,
            },
        )

    await db.commit()

    # Reload with student relation
    refreshed = await repo.get_decision_by_id(db, decision_id)
    if refreshed is None:
        raise NotFoundError("CouncilStudentDecision", decision_id)

    # Load student for name
    from sqlalchemy.orm import selectinload
    from sqlalchemy import select as sa_select
    from app.models.grade import CouncilStudentDecision as CSD

    stmt = (
        sa_select(CSD)
        .where(CSD.id == decision_id)
        .options(selectinload(CSD.student))
    )
    result = await db.execute(stmt)
    refreshed = result.scalar_one_or_none()
    if refreshed is None:
        raise NotFoundError("CouncilStudentDecision", decision_id)

    return _build_decision_response(refreshed)
