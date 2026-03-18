"""Service inscriptions — logique métier CRUD + frais automatiques."""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditAction, audit_log
from app.core.exceptions import BusinessValidationError, NotFoundError
from app.models.enrollment import Enrollment
from app.repositories import enrollment_repository as repo
from app.schemas.enrollment import (
    EnrollmentCreate,
    EnrollmentListResponse,
    EnrollmentResponse,
    EnrollmentUpdate,
)

logger = logging.getLogger(__name__)


def _to_response(enrollment: Enrollment) -> EnrollmentResponse:
    """Convertit un Enrollment ORM en EnrollmentResponse."""
    academic_year_name = (
        enrollment.academic_year.name
        if enrollment.academic_year
        else str(enrollment.academic_year_id)
    )
    fee_variant_id: int | None = None
    if enrollment.enrollment_fees:
        fee_variant_id = enrollment.enrollment_fees[0].fee_variant_id

    return EnrollmentResponse(
        id=enrollment.id,
        student_id=enrollment.student_id,
        class_id=enrollment.class_id,
        academic_year_id=enrollment.academic_year_id,
        academic_year_name=academic_year_name,
        status=enrollment.status,
        fee_variant_id=fee_variant_id,
        notes=enrollment.notes,
        created_by=enrollment.created_by,
        created_at=enrollment.created_at,
        updated_at=enrollment.updated_at,
    )


async def create_enrollment(
    db: AsyncSession,
    data: EnrollmentCreate,
    created_by: int,
) -> EnrollmentResponse:
    """Crée une inscription et le frais associé si fee_variant_id fourni."""
    # Valider que l'année scolaire existe
    academic_year = await repo.get_academic_year_by_id(db, data.academic_year_id)
    if academic_year is None:
        raise BusinessValidationError(f"AcademicYear {data.academic_year_id} not found")

    async with db.begin_nested():
        enrollment = await repo.create_enrollment(
            db,
            student_id=data.student_id,
            class_id=data.class_id,
            academic_year_id=data.academic_year_id,
            created_by=created_by,
            notes=data.notes,
        )

        if data.fee_variant_id is not None:
            await repo.create_enrollment_fee(
                db,
                enrollment_id=enrollment.id,
                fee_variant_id=data.fee_variant_id,
            )

    await db.commit()

    # Recharger avec les relations pour la réponse
    refreshed = await repo.get_enrollment_by_id(db, enrollment.id)
    assert refreshed is not None

    await audit_log(
        db,
        entity_type="enrollment",
        action=AuditAction.CREATE,
        user_id=created_by,
        entity_id=enrollment.id,
        new_values=data.model_dump(),
    )
    await db.commit()

    return _to_response(refreshed)


async def list_enrollments(
    db: AsyncSession,
    *,
    class_id: int | None = None,
    status: str | None = None,
    academic_year_id: int | None = None,
    page: int = 1,
    size: int = 20,
) -> EnrollmentListResponse:
    """Retourne une page d'inscriptions."""
    enrollments, total = await repo.list_enrollments(
        db,
        class_id=class_id,
        status=status,
        academic_year_id=academic_year_id,
        page=page,
        size=size,
    )
    return EnrollmentListResponse(
        items=[_to_response(e) for e in enrollments],
        total=total,
        page=page,
        size=size,
    )


async def get_enrollment(db: AsyncSession, enrollment_id: int) -> EnrollmentResponse:
    """Retourne une inscription par ID ou lève 404."""
    enrollment = await repo.get_enrollment_by_id(db, enrollment_id)
    if enrollment is None:
        raise NotFoundError("Enrollment", enrollment_id)
    return _to_response(enrollment)


async def update_enrollment(
    db: AsyncSession,
    enrollment_id: int,
    data: EnrollmentUpdate,
    updated_by: int,
) -> EnrollmentResponse:
    """Met à jour une inscription (patch partiel)."""
    enrollment = await repo.get_enrollment_by_id(db, enrollment_id)
    if enrollment is None:
        raise NotFoundError("Enrollment", enrollment_id)

    old_values = {"status": enrollment.status, "notes": enrollment.notes}

    await repo.update_enrollment(
        db,
        enrollment,
        status=data.status,
        notes=data.notes,
    )
    await db.commit()

    await audit_log(
        db,
        entity_type="enrollment",
        action=AuditAction.UPDATE,
        user_id=updated_by,
        entity_id=enrollment_id,
        old_values=old_values,
        new_values=data.model_dump(exclude_none=True),
    )
    await db.commit()

    refreshed = await repo.get_enrollment_by_id(db, enrollment_id)
    assert refreshed is not None
    return _to_response(refreshed)


async def delete_enrollment(
    db: AsyncSession,
    enrollment_id: int,
    deleted_by: int,
) -> None:
    """Supprime une inscription ou lève 404."""
    enrollment = await repo.get_enrollment_by_id(db, enrollment_id)
    if enrollment is None:
        raise NotFoundError("Enrollment", enrollment_id)

    await repo.delete_enrollment(db, enrollment)
    await db.commit()

    await audit_log(
        db,
        entity_type="enrollment",
        action=AuditAction.DELETE,
        user_id=deleted_by,
        entity_id=enrollment_id,
    )
    await db.commit()
