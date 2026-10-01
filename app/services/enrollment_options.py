"""Souscriptions d'une inscription aux options de frais facultatifs."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditAction, audit_log
from app.core.audit_values import frozen
from app.core.exceptions import BusinessValidationError, NotFoundError
from app.models.enrollment import StudentOption
from app.models.fee import OptionalFeeOption
from app.repositories import enrollment_repository as repo


async def subscribe_optional_fee(
    db: AsyncSession,
    enrollment_id: int,
    optional_fee_option_id: int,
    created_by: int,
) -> dict:
    """Souscrit un élève à une option de frais facultatif.

    Crée un StudentOption. Idempotent : si déjà souscrit, retourne l'existant.
    """
    await _ensure_option_matches_enrollment(db, enrollment_id, optional_fee_option_id)

    # Idempotent : une souscription existante est rendue telle quelle.
    existing_stmt = select(StudentOption).where(
        StudentOption.enrollment_id == enrollment_id,
        StudentOption.optional_fee_option_id == optional_fee_option_id,
    )
    existing = (await db.execute(existing_stmt)).scalar_one_or_none()
    if existing is not None:
        return {"id": existing.id, "already_subscribed": True}

    student_option = StudentOption(
        enrollment_id=enrollment_id,
        optional_fee_option_id=optional_fee_option_id,
        quantity=1,
    )
    db.add(student_option)
    await db.flush()
    await audit_log(
        db,
        entity_type="student_option",
        action=AuditAction.CREATE,
        user_id=created_by,
        entity_id=student_option.id,
        new_values={
            "enrollment_id": enrollment_id,
            "optional_fee_option_id": optional_fee_option_id,
        },
    )
    return {"id": student_option.id, "already_subscribed": False}


async def _ensure_option_matches_enrollment(
    db: AsyncSession, enrollment_id: int, optional_fee_option_id: int
) -> None:
    """L'inscription et l'option existent, et l'option vaut pour la même année."""
    enrollment = await repo.get_enrollment_by_id(db, enrollment_id)
    if enrollment is None:
        raise NotFoundError("Enrollment", enrollment_id)
    stmt = select(OptionalFeeOption).where(OptionalFeeOption.id == optional_fee_option_id)
    option = (await db.execute(stmt)).scalar_one_or_none()
    if option is None:
        raise NotFoundError("OptionalFeeOption", optional_fee_option_id)
    if option.academic_year_id != enrollment.academic_year_id:
        raise BusinessValidationError(
            "L'option de frais n'appartient pas à la même année scolaire que l'inscription"
        )


async def unsubscribe_optional_fee(
    db: AsyncSession,
    enrollment_id: int,
    option_id: int,
    deleted_by: int,
) -> None:
    """Désinscrit un élève d'une option de frais facultatif.

    Supprime le StudentOption correspondant.
    """
    stmt = select(StudentOption).where(
        StudentOption.enrollment_id == enrollment_id,
        StudentOption.optional_fee_option_id == option_id,
    )
    student_option = (await db.execute(stmt)).scalar_one_or_none()
    if student_option is None:
        raise NotFoundError("StudentOption", option_id)

    option_id_for_audit = student_option.id
    disparu = frozen(student_option, "enrollment_id", "optional_fee_option_id", "quantity")
    await db.delete(student_option)
    await db.flush()

    await audit_log(
        db,
        entity_type="student_option",
        action=AuditAction.DELETE,
        user_id=deleted_by,
        entity_id=option_id_for_audit,
        old_values=disparu,
    )
