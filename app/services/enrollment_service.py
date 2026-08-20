"""Service inscriptions — CRUD, inscription couplee eleve+inscription, options.

La corbeille vit dans `enrollment_archive`, les frais dans `enrollment_fees` :
ce fichier portait cinq sujets sans rapport, et plus personne ne le relisait
en entier.
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditAction, audit_log
from app.core.exceptions import BusinessValidationError, NotFoundError
from app.core.security import hash_password
from app.models.academic import AcademicYear, SchoolSettings
from app.models.enrollment import Enrollment, EnrollmentStatus, StudentOption
from app.models.fee import OptionalFeeOption
from app.models.user import Parent, ParentStudent, Student, User, UserRoleEnum
from app.repositories import enrollment_repository as repo
from app.schemas.enrollment import (
    EnrollmentCreate,
    EnrollmentListResponse,
    EnrollmentResponse,
    EnrollmentUpdate,
    EnrollmentWithStudentCreate,
    ReEnrollmentCreate,
)
from app.services import enrollment_fees
from app.services.matricule_service import generate_enrollment_number

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
        enrolled_count = await repo.count_active_enrollments_for_class(
            db, data.class_id, data.academic_year_id
        )
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
            assignment_status=data.assignment_status,
            assignment_decision_number=data.assignment_decision_number,
        )

        # Créer un enrollment_fee explicite si fee_variant_id fourni (rétrocompat)
        if data.fee_variant_id is not None:
            await repo.create_enrollment_fee(
                db,
                enrollment_id=enrollment.id,
                fee_variant_id=data.fee_variant_id,
            )

        # Auto-créer les enrollment_fees pour tous les frais obligatoires
        await enrollment_fees.create_mandatory_enrollment_fees(
            db,
            enrollment.id,
            data.class_id,
            data.academic_year_id,
            enrollment.assignment_status,
        )

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
    search: str | None = None,
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
        search=search,
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
    """Met à jour une inscription (patch partiel). Si class_id change, régénère les frais."""
    enrollment = await repo.get_enrollment_by_id(db, enrollment_id)
    if enrollment is None:
        raise NotFoundError("Enrollment", enrollment_id)

    old_values = {
        "status": enrollment.status,
        "notes": enrollment.notes,
        "class_id": enrollment.class_id,
    }
    class_changed = data.class_id is not None and data.class_id != enrollment.class_id

    async with db.begin_nested():
        # Si changement de classe, vérifier existence et capacité
        if class_changed:
            new_class = await repo.get_class_by_id_for_update(db, data.class_id)
            if new_class is None:
                raise BusinessValidationError(f"Class {data.class_id} not found")
            enrolled_count = await repo.count_active_enrollments_for_class(
                db, data.class_id, enrollment.academic_year_id
            )
            if enrolled_count >= new_class.max_students:
                raise BusinessValidationError(
                    f"Class {data.class_id} is full ({new_class.max_students} students max)"
                )

        await repo.update_enrollment(
            db,
            enrollment,
            status=data.status,
            notes=data.notes,
            class_id=data.class_id,
        )

        # Régénérer les frais obligatoires si la classe a changé
        if class_changed:
            await enrollment_fees.regenerate_enrollment_fees(
                db, enrollment_id, regenerated_by=updated_by
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


async def validate_enrollment(
    db: AsyncSession,
    enrollment_id: int,
    validated_by: int,
) -> EnrollmentResponse:
    """Transitionne une inscription `prospect` ou `en_validation` vers `valide`.

    Endpoint dédié (pas un PATCH générique) : audit log porte
    `action=validate` plutôt que `update`, et le transition guard refuse
    explicitement les autres statuts avec un message clair côté admin.
    """
    enrollment = await repo.get_enrollment_by_id(db, enrollment_id)
    if enrollment is None:
        raise NotFoundError("Enrollment", enrollment_id)

    previous_status = enrollment.status
    if previous_status == EnrollmentStatus.VALIDE:
        raise BusinessValidationError("Cette inscription est déjà validée.")
    if previous_status not in (EnrollmentStatus.PROSPECT, EnrollmentStatus.EN_VALIDATION):
        raise BusinessValidationError(
            f"Impossible de valider une inscription au statut « {previous_status.value} »."
        )

    async with db.begin_nested():
        await repo.update_enrollment(db, enrollment, status=EnrollmentStatus.VALIDE)
        await audit_log(
            db,
            entity_type="enrollment",
            action=AuditAction.UPDATE,
            user_id=validated_by,
            entity_id=enrollment_id,
            old_values={"status": previous_status.value},
            new_values={"status": EnrollmentStatus.VALIDE.value, "transition": "validate"},
        )

    await db.commit()

    refreshed = await repo.get_enrollment_by_id(db, enrollment_id)
    if refreshed is None:
        raise NotFoundError("Enrollment", enrollment_id)
    return _to_response(refreshed)




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
        enrolled_count = await repo.count_active_enrollments_for_class(
            db, data.class_id, data.academic_year_id
        )
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
                    db,
                    school,
                    class_data=class_,
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
            parent_user_id = None

            # If email + password provided, create a User account for the parent
            if data.parent.email and data.parent.password:
                existing_user = (
                    await db.execute(select(User).where(User.email == data.parent.email))
                ).scalar_one_or_none()
                if existing_user:
                    raise BusinessValidationError(
                        f"L'email parent {data.parent.email} est déjà utilisé"
                    )
                parent_user = User(
                    email=data.parent.email,
                    hashed_password=hash_password(data.parent.password),
                    role=UserRoleEnum.PARENT,
                )
                db.add(parent_user)
                await db.flush()
                parent_user_id = parent_user.id

                # Assign parent role via user_roles table
                from app.models.permission import Role
                from app.models.permission import UserRole as UserRoleModel

                role_stmt = select(Role).where(Role.name == "parent")
                role = (await db.execute(role_stmt)).scalar_one_or_none()
                if role:
                    db.add(UserRoleModel(user_id=parent_user.id, role_id=role.id))
                    await db.flush()

            parent = Parent(
                first_name=data.parent.first_name,
                last_name=data.parent.last_name,
                phone=data.parent.phone,
                email=data.parent.email,
                user_id=parent_user_id,
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
            assignment_status=data.assignment_status,
            assignment_decision_number=data.assignment_decision_number,
        )

        # 4. Create enrollment fee if variant provided (rétrocompat)
        if data.fee_variant_id is not None:
            await repo.create_enrollment_fee(
                db,
                enrollment_id=enrollment.id,
                fee_variant_id=data.fee_variant_id,
            )

        # 5. Auto-créer les enrollment_fees pour tous les frais obligatoires
        await enrollment_fees.create_mandatory_enrollment_fees(
            db,
            enrollment.id,
            data.class_id,
            data.academic_year_id,
            enrollment.assignment_status,
        )

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
# Optional fee subscriptions
# ---------------------------------------------------------------------------


async def subscribe_optional_fee(
    db: AsyncSession,
    enrollment_id: int,
    optional_fee_option_id: int,
    created_by: int,
) -> dict:
    """Souscrit un élève à une option de frais facultatif.

    Crée un StudentOption. Idempotent : si déjà souscrit, retourne l'existant.
    """
    enrollment = await repo.get_enrollment_by_id(db, enrollment_id)
    if enrollment is None:
        raise NotFoundError("Enrollment", enrollment_id)

    # Vérifier que l'option existe et appartient à la même année scolaire
    stmt = select(OptionalFeeOption).where(OptionalFeeOption.id == optional_fee_option_id)
    option = (await db.execute(stmt)).scalar_one_or_none()
    if option is None:
        raise NotFoundError("OptionalFeeOption", optional_fee_option_id)

    if option.academic_year_id != enrollment.academic_year_id:
        raise BusinessValidationError(
            "L'option de frais n'appartient pas à la même année scolaire que l'inscription"
        )

    # Vérifier si déjà souscrit (idempotent)
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
    await db.delete(student_option)
    await db.flush()

    await audit_log(
        db,
        entity_type="student_option",
        action=AuditAction.DELETE,
        user_id=deleted_by,
        entity_id=option_id_for_audit,
    )
