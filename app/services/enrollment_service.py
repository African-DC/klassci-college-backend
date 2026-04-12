"""Service inscriptions — logique métier CRUD + frais automatiques."""

import logging
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.audit import AuditAction, audit_log
from app.core.exceptions import BusinessValidationError, NotFoundError
from app.models.academic import AcademicYear, Class, SchoolSettings
from app.models.enrollment import Enrollment, EnrollmentStatus
from app.models.fee import EnrollmentFee, FeeCategory, FeeVariant
from app.models.user import Parent, ParentStudent, Student
from app.repositories import enrollment_repository as repo
from app.services.matricule_service import generate_enrollment_number
from app.schemas.enrollment import (
    EnrollmentCreate,
    EnrollmentListResponse,
    EnrollmentResponse,
    EnrollmentUpdate,
    EnrollmentWithStudentCreate,
    FeeVariantResponse,
    ReEnrollmentCreate,
)

logger = logging.getLogger(__name__)

_VALID_STATUSES = {s.value for s in EnrollmentStatus}


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
        student_first_name=enrollment.student.first_name if enrollment.student else None,
        student_last_name=enrollment.student.last_name if enrollment.student else None,
        class_name=enrollment.class_.name if enrollment.class_ else None,
    )


async def create_enrollment(
    db: AsyncSession,
    data: EnrollmentCreate,
    created_by: int,
) -> EnrollmentResponse:
    """Crée une inscription et le frais associé si fee_variant_id fourni."""
    # Valider que l'année scolaire existe (hors transaction — lecture seule)
    academic_year = await repo.get_academic_year_by_id(db, data.academic_year_id)
    if academic_year is None:
        raise BusinessValidationError(f"AcademicYear {data.academic_year_id} not found")

    # Tout dans une seule transaction avec FOR UPDATE pour éviter les race conditions
    async with db.begin_nested():
        # Garde capacité classe — FOR UPDATE verrouille la ligne pour éviter la race condition
        class_ = await repo.get_class_by_id_for_update(db, data.class_id)
        if class_ is None:
            raise BusinessValidationError(f"Class {data.class_id} not found")
        enrolled_count = await repo.count_active_enrollments_for_class(db, data.class_id)
        if enrolled_count >= class_.max_students:
            raise BusinessValidationError(
                f"Class {data.class_id} is full ({class_.max_students} students max)"
            )

        # Garde doublon dans la transaction
        existing = await repo.get_active_enrollment(db, data.student_id, data.academic_year_id)
        if existing is not None:
            raise BusinessValidationError(
                f"Student {data.student_id} already has an active enrollment for this academic year"
            )

        enrollment = await repo.create_enrollment(
            db,
            student_id=data.student_id,
            class_id=data.class_id,
            academic_year_id=data.academic_year_id,
            created_by=created_by,
            notes=data.notes,
        )

        # Créer un enrollment_fee explicite si fee_variant_id fourni (rétrocompat)
        if data.fee_variant_id is not None:
            await repo.create_enrollment_fee(
                db,
                enrollment_id=enrollment.id,
                fee_variant_id=data.fee_variant_id,
            )

        # Auto-créer les enrollment_fees pour tous les frais obligatoires
        await _create_mandatory_enrollment_fees(db, enrollment.id, data.class_id)

        await audit_log(
            db,
            entity_type="enrollment",
            action=AuditAction.CREATE,
            user_id=created_by,
            entity_id=enrollment.id,
            new_values=data.model_dump(),
        )

    await db.commit()

    refreshed = await repo.get_enrollment_by_id(db, enrollment.id)
    if refreshed is None:
        raise NotFoundError("Enrollment", enrollment.id)
    return _to_response(refreshed)


async def list_enrollments(
    db: AsyncSession,
    *,
    class_id: int | None = None,
    student_id: int | None = None,
    status: str | None = None,
    academic_year_id: int | None = None,
    page: int = 1,
    size: int = 20,
) -> EnrollmentListResponse:
    """Retourne une page d'inscriptions."""
    # Valider le filtre status
    if status is not None and status not in _VALID_STATUSES:
        raise BusinessValidationError(f"Invalid status '{status}'. Valid: {_VALID_STATUSES}")

    enrollments, total = await repo.list_enrollments(
        db,
        class_id=class_id,
        student_id=student_id,
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

    async with db.begin_nested():
        await repo.update_enrollment(
            db,
            enrollment,
            status=data.status,
            notes=data.notes,
        )
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
    if refreshed is None:
        raise NotFoundError("Enrollment", enrollment_id)
    return _to_response(refreshed)


async def delete_enrollment(
    db: AsyncSession,
    enrollment_id: int,
    deleted_by: int,
) -> None:
    """Supprime une inscription ou lève 404. Bloque si statut valide avec paiements."""
    enrollment = await repo.get_enrollment_by_id(db, enrollment_id)
    if enrollment is None:
        raise NotFoundError("Enrollment", enrollment_id)

    if enrollment.status == EnrollmentStatus.VALIDE and enrollment.enrollment_fees:
        has_payments = any(ef.payments for ef in enrollment.enrollment_fees)
        if has_payments:
            raise BusinessValidationError(
                "Cannot delete a validated enrollment with existing payments"
            )

    async with db.begin_nested():
        await repo.delete_enrollment(db, enrollment)
        await audit_log(
            db,
            entity_type="enrollment",
            action=AuditAction.DELETE,
            user_id=deleted_by,
            entity_id=enrollment_id,
        )

    await db.commit()


# ---------------------------------------------------------------------------
# Current academic year helper
# ---------------------------------------------------------------------------


async def _get_current_academic_year(db: AsyncSession) -> AcademicYear:
    """Retourne l'annee scolaire courante ou leve une erreur metier."""
    stmt = select(AcademicYear).where(AcademicYear.is_current == True)  # noqa: E712
    result = await db.execute(stmt)
    year = result.scalar_one_or_none()
    if not year:
        raise BusinessValidationError(
            "Aucune annee academique courante definie. "
            "Veuillez configurer l'annee courante dans les parametres."
        )
    return year


# ---------------------------------------------------------------------------
# Composite enrollment: student + parent + enrollment in one transaction
# ---------------------------------------------------------------------------


async def create_enrollment_with_student(
    db: AsyncSession,
    data: EnrollmentWithStudentCreate,
    created_by: int,
) -> EnrollmentResponse:
    """Cree un eleve, un parent optionnel, et une inscription en une transaction."""
    # Resolve academic year
    academic_year_id = data.academic_year_id
    if academic_year_id is None:
        current = await _get_current_academic_year(db)
        academic_year_id = current.id
    else:
        ay = await repo.get_academic_year_by_id(db, academic_year_id)
        if ay is None:
            raise BusinessValidationError(f"AcademicYear {academic_year_id} not found")

    async with db.begin_nested():
        # Capacity guard
        class_ = await repo.get_class_by_id_for_update(db, data.class_id)
        if class_ is None:
            raise BusinessValidationError(f"Class {data.class_id} not found")
        enrolled_count = await repo.count_active_enrollments_for_class(db, data.class_id)
        if enrolled_count >= class_.max_students:
            raise BusinessValidationError(
                f"Class {data.class_id} is full ({class_.max_students} students max)"
            )

        # 1. Create student
        student = Student(
            first_name=data.first_name,
            last_name=data.last_name,
            birth_date=data.birth_date,
            genre=data.genre,
            enrollment_number=data.enrollment_number,
        )
        db.add(student)
        await db.flush()

        # Auto-generate enrollment number if pattern configured and none provided
        if not data.enrollment_number:
            settings_result = await db.execute(select(SchoolSettings).limit(1))
            school = settings_result.scalar_one_or_none()
            if school and school.enrollment_number_pattern:
                enrollment_num = await generate_enrollment_number(
                    db, school, class_data=class_,
                )
                student.enrollment_number = enrollment_num
                await db.flush()
            else:
                raise BusinessValidationError(
                    "Le matricule est obligatoire. "
                    "Configurez un pattern automatique ou saisissez-le manuellement."
                )

        # 2. Create parent if provided
        if data.parent:
            parent = Parent(
                first_name=data.parent.first_name,
                last_name=data.parent.last_name,
                phone=data.parent.phone,
                email=data.parent.email,
            )
            db.add(parent)
            await db.flush()
            link = ParentStudent(
                parent_id=parent.id,
                student_id=student.id,
                relationship_type=data.parent.relationship_type,
            )
            db.add(link)
            await db.flush()

        # 3. Create enrollment (reuses capacity check done above)
        enrollment = await repo.create_enrollment(
            db,
            student_id=student.id,
            class_id=data.class_id,
            academic_year_id=academic_year_id,
            created_by=created_by,
            notes=data.notes,
        )

        # 4. Create enrollment fee if variant provided (rétrocompat)
        if data.fee_variant_id is not None:
            await repo.create_enrollment_fee(
                db,
                enrollment_id=enrollment.id,
                fee_variant_id=data.fee_variant_id,
            )

        # 5. Auto-créer les enrollment_fees pour tous les frais obligatoires
        await _create_mandatory_enrollment_fees(db, enrollment.id, data.class_id)

        await audit_log(
            db,
            entity_type="enrollment",
            action=AuditAction.CREATE,
            user_id=created_by,
            entity_id=enrollment.id,
            new_values={
                "student_name": f"{data.first_name} {data.last_name}",
                "with_student": True,
                "class_id": data.class_id,
                "academic_year_id": academic_year_id,
            },
        )

    await db.commit()

    refreshed = await repo.get_enrollment_by_id(db, enrollment.id)
    if refreshed is None:
        raise NotFoundError("Enrollment", enrollment.id)
    return _to_response(refreshed)


async def re_enroll_student(
    db: AsyncSession,
    data: ReEnrollmentCreate,
    created_by: int,
) -> EnrollmentResponse:
    """Re-inscrit un eleve existant dans une nouvelle classe/annee."""
    # Resolve academic year
    academic_year_id = data.academic_year_id
    if academic_year_id is None:
        current = await _get_current_academic_year(db)
        academic_year_id = current.id
    else:
        ay = await repo.get_academic_year_by_id(db, academic_year_id)
        if ay is None:
            raise BusinessValidationError(f"AcademicYear {academic_year_id} not found")

    # Use existing create_enrollment logic (handles capacity + duplicate guard)
    enrollment_data = EnrollmentCreate(
        student_id=data.student_id,
        class_id=data.class_id,
        academic_year_id=academic_year_id,
        fee_variant_id=data.fee_variant_id,
        notes=data.notes,
    )
    return await create_enrollment(db, enrollment_data, created_by=created_by)


# ---------------------------------------------------------------------------
# Mandatory fee variants helper
# ---------------------------------------------------------------------------


async def _get_mandatory_fee_variants(
    db: AsyncSession,
    class_id: int,
) -> list[FeeVariant]:
    """Retourne les FeeVariants obligatoires applicables à une classe.

    Résout par level_id + series_id + academic_year_id de la classe,
    filtrés aux catégories is_mandatory=True.
    """
    stmt = select(Class).where(Class.id == class_id)
    result = await db.execute(stmt)
    class_ = result.scalar_one_or_none()
    if class_ is None:
        raise BusinessValidationError(f"Class {class_id} not found")

    if class_.series_id:
        series_condition = or_(
            FeeVariant.series_id == class_.series_id,
            FeeVariant.series_id.is_(None),
        )
    else:
        series_condition = FeeVariant.series_id.is_(None)

    stmt = (
        select(FeeVariant)
        .join(FeeCategory, FeeVariant.fee_category_id == FeeCategory.id)
        .where(
            FeeVariant.academic_year_id == class_.academic_year_id,
            FeeVariant.level_id == class_.level_id,
            series_condition,
            FeeCategory.is_mandatory == True,  # noqa: E712
        )
    )
    rows = (await db.execute(stmt)).scalars().all()
    return list(rows)


async def _create_mandatory_enrollment_fees(
    db: AsyncSession,
    enrollment_id: int,
    class_id: int,
) -> None:
    """Crée les EnrollmentFee pour tous les frais obligatoires d'une classe.

    Idempotent : ne crée pas de doublons si un enrollment_fee existe déjà
    pour un fee_variant donné.
    """
    variants = await _get_mandatory_fee_variants(db, class_id)
    if not variants:
        return

    # Récupérer les fee_variant_ids déjà liés à cette inscription
    existing_stmt = (
        select(EnrollmentFee.fee_variant_id)
        .where(EnrollmentFee.enrollment_id == enrollment_id)
    )
    existing_ids = set((await db.execute(existing_stmt)).scalars().all())

    for variant in variants:
        if variant.id not in existing_ids:
            fee = EnrollmentFee(
                enrollment_id=enrollment_id,
                fee_variant_id=variant.id,
                amount=variant.amount,
            )
            db.add(fee)

    await db.flush()


# ---------------------------------------------------------------------------
# Fee variant resolution by class
# ---------------------------------------------------------------------------


async def get_applicable_fee_variants(
    db: AsyncSession,
    class_id: int,
) -> list[FeeVariantResponse]:
    """Retourne les fee variants applicables pour une classe donnée.

    Résout par level_id + series_id + academic_year_id de la classe.
    Si la classe a une series_id, on prend les variants avec cette série
    OU ceux sans série (globaux pour le niveau). Sinon, uniquement series_id IS NULL.
    """
    stmt = select(Class).where(Class.id == class_id)
    result = await db.execute(stmt)
    class_ = result.scalar_one_or_none()
    if class_ is None:
        raise BusinessValidationError(f"Class {class_id} not found")

    # Variants matching this level + academic year
    # series_id: exact match OR NULL (applicable à tout le niveau)
    if class_.series_id:
        series_condition = or_(
            FeeVariant.series_id == class_.series_id,
            FeeVariant.series_id.is_(None),
        )
    else:
        series_condition = FeeVariant.series_id.is_(None)

    stmt = (
        select(FeeVariant)
        .options(selectinload(FeeVariant.category))
        .where(
            FeeVariant.academic_year_id == class_.academic_year_id,
            FeeVariant.level_id == class_.level_id,
            series_condition,
        )
        .order_by(FeeVariant.fee_category_id, FeeVariant.id)
    )
    rows = (await db.execute(stmt)).scalars().all()

    return [
        FeeVariantResponse(
            id=fv.id,
            fee_category_id=fv.fee_category_id,
            category_name=fv.category.name if fv.category else str(fv.fee_category_id),
            level_id=fv.level_id,
            series_id=fv.series_id,
            academic_year_id=fv.academic_year_id,
            amount=fv.amount,
            description=fv.description,
        )
        for fv in rows
    ]
