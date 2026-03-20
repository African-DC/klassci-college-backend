"""Repository inscriptions — accès DB pour Enrollment et EnrollmentFee."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.academic import AcademicYear, Class
from app.models.enrollment import Enrollment, EnrollmentStatus
from app.models.fee import EnrollmentFee, FeeVariant


async def get_enrollment_by_id(db: AsyncSession, enrollment_id: int) -> Enrollment | None:
    """Retourne une inscription par ID avec ses relations chargées."""
    stmt = (
        select(Enrollment)
        .where(Enrollment.id == enrollment_id)
        .options(
            selectinload(Enrollment.academic_year),
            selectinload(Enrollment.enrollment_fees).selectinload(EnrollmentFee.fee_variant),
        )
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def list_enrollments(
    db: AsyncSession,
    *,
    class_id: int | None = None,
    status: str | None = None,
    academic_year_id: int | None = None,
    page: int = 1,
    size: int = 20,
) -> tuple[list[Enrollment], int]:
    """Retourne une page d'inscriptions avec le total."""
    base = select(Enrollment).options(
        selectinload(Enrollment.academic_year),
        selectinload(Enrollment.enrollment_fees).selectinload(EnrollmentFee.fee_variant),
    )
    if class_id is not None:
        base = base.where(Enrollment.class_id == class_id)
    if status is not None:
        base = base.where(Enrollment.status == status)
    if academic_year_id is not None:
        base = base.where(Enrollment.academic_year_id == academic_year_id)

    count_stmt = select(func.count()).select_from(base.subquery())
    total: int = (await db.execute(count_stmt)).scalar() or 0

    stmt = base.offset((page - 1) * size).limit(size).order_by(Enrollment.id.desc())
    rows = (await db.execute(stmt)).scalars().all()
    return list(rows), total


async def create_enrollment(
    db: AsyncSession,
    *,
    student_id: int,
    class_id: int,
    academic_year_id: int,
    created_by: int | None,
    notes: str | None,
) -> Enrollment:
    """Crée une inscription et la flush pour obtenir l'ID."""
    enrollment = Enrollment(
        student_id=student_id,
        class_id=class_id,
        academic_year_id=academic_year_id,
        created_by=created_by,
        notes=notes,
    )
    db.add(enrollment)
    await db.flush()
    return enrollment


async def create_enrollment_fee(
    db: AsyncSession,
    *,
    enrollment_id: int,
    fee_variant_id: int,
) -> EnrollmentFee:
    """Crée un EnrollmentFee en récupérant le montant depuis FeeVariant."""
    variant_stmt = select(FeeVariant).where(FeeVariant.id == fee_variant_id)
    variant = (await db.execute(variant_stmt)).scalar_one_or_none()
    if variant is None:
        from app.core.exceptions import NotFoundError

        raise NotFoundError("FeeVariant", fee_variant_id)

    fee = EnrollmentFee(
        enrollment_id=enrollment_id,
        fee_variant_id=fee_variant_id,
        amount=variant.amount,
    )
    db.add(fee)
    await db.flush()
    return fee


async def update_enrollment(
    db: AsyncSession,
    enrollment: Enrollment,
    *,
    status: str | None = None,
    notes: str | None = None,
) -> Enrollment:
    """Met à jour les champs modifiables d'une inscription."""
    if status is not None:
        enrollment.status = status
    if notes is not None:
        enrollment.notes = notes
    await db.flush()
    return enrollment


async def delete_enrollment(db: AsyncSession, enrollment: Enrollment) -> None:
    """Supprime une inscription."""
    await db.delete(enrollment)
    await db.flush()


async def get_active_enrollment(
    db: AsyncSession, student_id: int, academic_year_id: int
) -> Enrollment | None:
    """Retourne une inscription active existante (pour détecter les doublons)."""
    stmt = select(Enrollment).where(
        Enrollment.student_id == student_id,
        Enrollment.academic_year_id == academic_year_id,
        Enrollment.status != EnrollmentStatus.ANNULE,
        Enrollment.status != EnrollmentStatus.REJETE,
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_class_by_id(db: AsyncSession, class_id: int) -> Class | None:
    """Retourne une classe par ID."""
    return (await db.execute(select(Class).where(Class.id == class_id))).scalar_one_or_none()


async def count_active_enrollments_for_class(db: AsyncSession, class_id: int) -> int:
    """Compte les inscriptions valides dans une classe."""
    stmt = select(func.count()).select_from(Enrollment).where(
        Enrollment.class_id == class_id,
        Enrollment.status == EnrollmentStatus.VALIDE,
    )
    return (await db.execute(stmt)).scalar() or 0


async def get_academic_year_by_id(db: AsyncSession, academic_year_id: int) -> AcademicYear | None:
    """Retourne une année scolaire par ID."""
    stmt = select(AcademicYear).where(AcademicYear.id == academic_year_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()
