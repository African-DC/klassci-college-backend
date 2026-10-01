"""Inscription couplée : l'élève, son parent éventuel et l'inscription d'un seul geste.

C'est le chemin du formulaire « Nouvelle inscription ». Il vivait dans
`enrollment_service`, qui dépassait la taille qu'on relit d'une traite.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditAction, audit_log
from app.core.exceptions import BusinessValidationError, NotFoundError
from app.core.security import hash_password
from app.models.academic import Class, SchoolSettings
from app.models.user import Parent, ParentStudent, Student, User, UserRoleEnum
from app.repositories import enrollment_repository as repo
from app.schemas.enrollment import EnrollmentResponse, EnrollmentWithStudentCreate, ParentInput
from app.services import (
    enrollment_arrears,
    enrollment_fees,
    enrollment_notifications,
    enrollment_profile,
)
from app.services.enrollment_arrears import ArrearsClearance
from app.services.enrollment_creation_helpers import (
    get_current_academic_year,
    nom_eleve,
    profil_a_retenir,
)
from app.services.enrollment_mapper import to_enrollment_response as _to_response
from app.services.matricule_service import generate_enrollment_number


async def create_enrollment_with_student(
    db: AsyncSession,
    data: EnrollmentWithStudentCreate,
    created_by: int,
    *,
    arrears: ArrearsClearance,
) -> EnrollmentResponse:
    """Cree un eleve, un parent optionnel, et une inscription en une transaction.

    La seconde porte vers `repo.create_enrollment`, et celle que le formulaire
    « Nouvelle inscription » emprunte. Garder l'autre seule ne servirait à
    rien : c'est ici qu'une réinscription saisie comme un nouvel élève
    passerait. Le garde n'a pas encore d'identifiant d'élève à lui donner — on
    est en train de le créer — il lui passe donc le matricule, seul point de
    rapprochement sûr avec un dossier déjà en base.
    """
    # Resolve academic year
    if data.academic_year_id is None:
        academic_year = await get_current_academic_year(db)
    else:
        academic_year = await repo.get_academic_year_by_id(db, data.academic_year_id)
        if academic_year is None:
            raise BusinessValidationError(f"AcademicYear {data.academic_year_id} not found")
    academic_year_id = academic_year.id

    # Même porte que dans `create_enrollment`, et à la même place : avant toute
    # écriture, hors transaction.
    await enrollment_arrears.ensure_enrollable(
        db,
        matricule=data.enrollment_number,
        year=academic_year,
        actor_id=created_by,
        clearance=arrears,
    )

    async with db.begin_nested():
        # Capacity guard
        class_ = await repo.get_class_by_id_for_update(db, data.class_id)
        if class_ is None:
            raise BusinessValidationError(f"Class {data.class_id} not found")
        enrolled_count = await repo.count_active_enrollments_for_class(
            db, data.class_id, academic_year_id
        )
        if enrolled_count >= class_.max_students:
            raise BusinessValidationError(
                f"Class {data.class_id} is full ({class_.max_students} students max)"
            )

        student = await _create_student(db, data, class_)

        # 2. Create parent if provided
        if data.parent:
            await _create_parent(db, data.parent, student.id)

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
            is_new_student=await profil_a_retenir(db, data, student.id, academic_year_id),
        )
        await enrollment_profile.apply_initial_profile(db, enrollment, data, academic_year)

        # 4. Create enrollment fee if variant provided (rétrocompat).
        # Même garde qu'à l'autre création : le tarif nommé doit viser cette
        # inscription, profil compris.
        if data.fee_variant_id is not None:
            await enrollment_fees.create_explicit_enrollment_fee(
                db,
                enrollment=enrollment,
                fee_variant_id=data.fee_variant_id,
            )

        # 5. Auto-créer les enrollment_fees pour tous les frais obligatoires
        await enrollment_fees.create_mandatory_enrollment_fees(
            db,
            enrollment.id,
            data.class_id,
            academic_year_id,
            enrollment.assignment_status,
            enrollment.is_new_student,
        )
        await enrollment_fees.apply_in_kind_deposits(
            db, enrollment.id, data.in_kind_deposits, deposited_by=created_by
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

    # Même avertissement que dans `create_enrollment`, et pour la même raison :
    # c'est ce chemin-ci que le formulaire « Nouvelle inscription » emprunte,
    # celui où la secrétaire saisit l'élève et son inscription d'un seul geste.
    # Sans cet appel, la chaîne restait muette précisément là où elle sert.
    await enrollment_notifications.prevenir_qu_il_faut_encaisser(
        db,
        enrollment_id=refreshed.id,
        student_name=nom_eleve(refreshed),
        class_name=refreshed.class_.name if refreshed.class_ else "",
        acteur_id=created_by,
    )
    return _to_response(refreshed)


async def _create_student(
    db: AsyncSession, data: EnrollmentWithStudentCreate, class_: Class
) -> Student:
    """Crée l'élève et lui donne son matricule, saisi ou généré."""
    # 1. Create student
    student = Student(
        first_name=data.first_name,
        last_name=data.last_name,
        birth_date=data.birth_date,
        birth_place=data.birth_place,
        genre=data.genre,
        nationality=data.nationality,
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
    return student


async def _create_parent(db: AsyncSession, parent_data: ParentInput, student_id: int) -> None:
    """Crée le parent, son compte s'il a un courriel et un mot de passe, et le lien."""
    parent_user_id = None

    # If email + password provided, create a User account for the parent
    if parent_data.email and parent_data.password:
        existing_user = (
            await db.execute(select(User).where(User.email == parent_data.email))
        ).scalar_one_or_none()
        if existing_user:
            raise BusinessValidationError(f"L'email parent {parent_data.email} est déjà utilisé")
        parent_user = User(
            email=parent_data.email,
            hashed_password=hash_password(parent_data.password),
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
        first_name=parent_data.first_name,
        last_name=parent_data.last_name,
        phone=parent_data.phone,
        email=parent_data.email,
        user_id=parent_user_id,
    )
    db.add(parent)
    await db.flush()
    link = ParentStudent(
        parent_id=parent.id,
        student_id=student_id,
        relationship_type=parent_data.relationship_type,
    )
    db.add(link)
    await db.flush()
