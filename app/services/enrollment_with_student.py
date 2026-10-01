"""Inscription couplée : l'élève, son parent éventuel et l'inscription d'un seul geste.

C'est le chemin du formulaire « Nouvelle inscription ». Il vivait dans
`enrollment_service`, qui dépassait la taille qu'on relit d'une traite.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessValidationError
from app.core.security import hash_password
from app.models.academic import Class, SchoolSettings
from app.models.user import Parent, ParentStudent, Student, User, UserRoleEnum
from app.schemas.enrollment import EnrollmentResponse, EnrollmentWithStudentCreate, ParentInput
from app.services import (
    enrollment_arrears,
)
from app.services import enrollment_creation_steps as steps
from app.services.enrollment_arrears import ArrearsClearance
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
    academic_year = await steps.resolve_academic_year(db, data.academic_year_id)

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
        class_ = await steps.ensure_class_has_room(db, data.class_id, academic_year.id)
        student = await _create_student(db, data, class_)
        if data.parent:
            await _create_parent(db, data.parent, student.id)
        enrollment = await steps.insert_enrollment(
            db, data, student_id=student.id, year=academic_year, created_by=created_by
        )
        await steps.attach_fees(
            db,
            enrollment,
            fee_variant_id=data.fee_variant_id,
            in_kind_deposits=data.in_kind_deposits,
            created_by=created_by,
        )
        await steps.audit_creation(
            db, enrollment, _summary(data, academic_year.id), created_by=created_by
        )

    # Prévient la caisse, comme l'autre création : c'est le chemin du formulaire.
    return await steps.finish_creation(db, enrollment.id, created_by=created_by)


def _summary(data: EnrollmentWithStudentCreate, academic_year_id: int) -> dict[str, object]:
    """Ce que le journal garde du formulaire, en plus de la fiche finale."""
    return {
        "student_name": f"{data.first_name} {data.last_name}",
        "with_student": True,
        "class_id": data.class_id,
        "academic_year_id": academic_year_id,
    }


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
