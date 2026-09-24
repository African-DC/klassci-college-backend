"""Service inscriptions — CRUD, inscription couplee eleve+inscription, options.

La corbeille vit dans `enrollment_archive`, les frais dans `enrollment_fees` :
ce fichier portait cinq sujets sans rapport, et plus personne ne le relisait
en entier.
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditAction, audit_log
from app.core.audit_values import frozen
from app.core.exceptions import BusinessValidationError, NotFoundError, PermissionDeniedError
from app.core.security import hash_password
from app.models.academic import AcademicYear, SchoolSettings
from app.models.enrollment import EnrollmentStatus, StudentOption
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
from app.services import (
    enrollment_arrears,
    enrollment_fees,
    enrollment_history,
    enrollment_notifications,
    enrollment_validation,
)
from app.services.enrollment_arrears import ArrearsClearance
from app.services.enrollment_mapper import to_enrollment_response as _to_response
from app.services.matricule_service import generate_enrollment_number

logger = logging.getLogger(__name__)

_VALID_STATUSES = {s.value for s in EnrollmentStatus}
#: Filtre d'écran « À valider » : prospect + en_validation, la queue du jour.
_FILTRE_STATUTS = _VALID_STATUSES | {"a_valider"}


async def _profil_a_retenir(
    db: AsyncSession,
    data: EnrollmentCreate | EnrollmentWithStudentCreate,
    student_id: int,
    academic_year_id: int,
) -> bool | None:
    """Le profil de l'inscription : celui du formulaire, ou celui qu'on déduit.

    Le corps sait dire trois choses, et il faut les distinguer toutes les
    trois :

    - `true` / `false` : le guichet a tranché, il l'emporte toujours. C'est
      lui qui a le dossier sous les yeux, la suggestion n'est qu'une aide.
    - `is_new_student: null` **envoyé** : le guichet dit explicitement qu'il ne
      tranche pas. On enregistre ce vide tel quel. Déduire ici démentirait
      l'écran, qui vient de promettre « non tranché ».
    - champ **absent** du corps : personne ne s'est prononcé, on lit
      l'historique. Si l'école ne l'a pas déclaré exploitable, la déduction
      rend `None` à son tour plutôt que d'inventer un montant.

    D'où la lecture de `model_fields_set` et non un test sur la valeur : `None`
    est ici une valeur métier, pas une absence.
    """
    if "is_new_student" in data.model_fields_set:
        return data.is_new_student
    return await enrollment_history.deduce_new_student(db, student_id, academic_year_id)


async def create_enrollment(
    db: AsyncSession,
    data: EnrollmentCreate,
    created_by: int,
    *,
    arrears: ArrearsClearance,
) -> EnrollmentResponse:
    """Crée une inscription et le frais associé si fee_variant_id fourni.

    `arrears` dit ce que l'appelant a le droit de faire, et de voir, face à une
    ardoise d'un exercice révolu. Il se résout au routeur — trois permissions
    lues en base — et se passe toujours explicitement : ce service ne connaît
    ni rôle ni slug, et un garde dont l'oubli est permissif n'est pas un garde.
    """
    # Valider que l'année scolaire existe (hors transaction — lecture seule)
    academic_year = await repo.get_academic_year_by_id(db, data.academic_year_id)
    if academic_year is None:
        raise BusinessValidationError(f"AcademicYear {data.academic_year_id} not found")

    # Porte de paiement — AVANT la transaction, et ce n'est pas un détail : le
    # garde n'a pas le droit de commettre au milieu d'un `begin_nested()`, il
    # validerait la moitié d'une inscription. Il lit, et laisse sa ligne de
    # journal au commit ci-dessous.
    await enrollment_arrears.ensure_enrollable(
        db,
        student_id=data.student_id,
        year=academic_year,
        actor_id=created_by,
        clearance=arrears,
    )

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
            is_new_student=await _profil_a_retenir(
                db, data, data.student_id, data.academic_year_id
            ),
        )

        # Créer un enrollment_fee explicite si fee_variant_id fourni (rétrocompat).
        # Le garde vit dans `enrollment_fees` : un tarif nommé par le client
        # doit viser cette inscription, sans quoi ce chemin poserait un montant
        # à profil sur une inscription dont le profil n'est pas tranché.
        if data.fee_variant_id is not None:
            await enrollment_fees.create_explicit_enrollment_fee(
                db,
                enrollment=enrollment,
                fee_variant_id=data.fee_variant_id,
            )

        # Auto-créer les enrollment_fees pour tous les frais obligatoires
        await enrollment_fees.create_mandatory_enrollment_fees(
            db,
            enrollment.id,
            data.class_id,
            data.academic_year_id,
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
            new_values=data.model_dump(),
        )

    await db.commit()

    refreshed = await repo.get_enrollment_by_id(db, enrollment.id)
    if refreshed is None:
        raise NotFoundError("Enrollment", enrollment.id)

    # Apres le commit : le dossier existe, quel que soit le sort de la cloche.
    await enrollment_notifications.prevenir_qu_il_faut_encaisser(
        db,
        enrollment_id=refreshed.id,
        student_name=_nom_eleve(refreshed),
        class_name=refreshed.class_.name if refreshed.class_ else "",
        acteur_id=created_by,
    )
    return _to_response(refreshed)


def _nom_eleve(enrollment: object) -> str:
    """Le nom affichable de l'élève, ou son matricule s'il manque."""
    student = getattr(enrollment, "student", None)
    if student is None:
        return "Un élève"
    parts = [getattr(student, "last_name", ""), getattr(student, "first_name", "")]
    nom = " ".join(p for p in parts if p).strip()
    return nom or getattr(student, "enrollment_number", "") or "Un élève"


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
    if status is not None and status not in _FILTRE_STATUTS:
        raise BusinessValidationError(f"Invalid status '{status}'. Valid: {_FILTRE_STATUTS}")

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
    en_attente = await enrollment_validation.awaiting_payment(db, (e.id for e in enrollments))
    return EnrollmentListResponse(
        items=[_to_response(e, awaiting_payment=e.id in en_attente) for e in enrollments],
        total=total,
        page=page,
        size=size,
    )


async def get_enrollment(db: AsyncSession, enrollment_id: int) -> EnrollmentResponse:
    """Retourne une inscription par ID ou lève 404."""
    enrollment = await repo.get_enrollment_by_id(db, enrollment_id)
    if enrollment is None:
        raise NotFoundError("Enrollment", enrollment_id)
    en_attente = await enrollment_validation.awaiting_payment(db, [enrollment_id])
    return _to_response(enrollment, awaiting_payment=enrollment_id in en_attente)


async def update_enrollment(
    db: AsyncSession,
    enrollment_id: int,
    data: EnrollmentUpdate,
    updated_by: int,
    *,
    peut_valider: bool = False,
) -> EnrollmentResponse:
    """Met à jour une inscription (patch partiel). Classe, profil ou affectation : régénère les frais.

    Passer le statut à « valide » est une validation, et passe par elle :
    même droit (`peut_valider`, lu par la route), même garde de versement,
    même refus des statuts terminaux, même trace au journal. Le formulaire
    d'édition renvoie le statut à chaque enregistrement : un statut déjà
    « valide » n'est pas une transition, et n'exige rien.
    """
    enrollment = await repo.get_enrollment_by_id(db, enrollment_id)
    if enrollment is None:
        raise NotFoundError("Enrollment", enrollment_id)

    validation = (
        data.status == EnrollmentStatus.VALIDE.value
        and enrollment.status != EnrollmentStatus.VALIDE
    )
    if validation and not peut_valider:
        raise PermissionDeniedError("enrollments:validate")
    # Le statut, s'il valide, passe par la validation plus bas ; tout le reste
    # s'écrit ici. Le journal de l'édition ne le compte donc pas deux fois.
    champs = data.model_fields_set - ({"status"} if validation else set())

    old_values = {
        "status": enrollment.status,
        "notes": enrollment.notes,
        "class_id": enrollment.class_id,
        "is_new_student": enrollment.is_new_student,
        "assignment_status": enrollment.assignment_status,
        "assignment_decision_number": enrollment.assignment_decision_number,
    }
    class_changed = data.class_id is not None and data.class_id != enrollment.class_id
    # `None` est une valeur ici, pas une absence : on regarde donc ce que le
    # client a réellement envoyé. Corriger le profil doit rejouer la grille,
    # sinon la case change et la facture reste celle de l'autre profil.
    profil_envoye = "is_new_student" in data.model_fields_set
    profil_change = profil_envoye and data.is_new_student != enrollment.is_new_student
    affectation_envoyee = "assignment_status" in data.model_fields_set
    decision_envoyee = "assignment_decision_number" in data.model_fields_set
    affectation_change = (
        affectation_envoyee and data.assignment_status != enrollment.assignment_status
    )

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
            status=None if validation else data.status,
            notes=data.notes,
            class_id=data.class_id,
            is_new_student=(data.is_new_student if profil_envoye else repo.UNSET),
            assignment_status=(data.assignment_status if affectation_envoyee else repo.UNSET),
            assignment_decision_number=(
                data.assignment_decision_number if decision_envoyee else repo.UNSET
            ),
        )

        # Régénérer les frais obligatoires si la classe, le profil ou
        # l'affectation a changé : chacun décide du tarif appliqué.
        if class_changed or profil_change or affectation_change:
            await enrollment_fees.regenerate_enrollment_fees(
                db, enrollment_id, regenerated_by=updated_by
            )

        # Après la régénération : la garde de versement lit la grille de frais
        # que l'inscription aura réellement, pas celle d'avant la modification.
        if validation:
            await enrollment_validation.appliquer_validation(db, enrollment, updated_by)

        if champs:
            await audit_log(
                db,
                entity_type="enrollment",
                action=AuditAction.UPDATE,
                user_id=updated_by,
                entity_id=enrollment_id,
                old_values=old_values,
                # Ce que le client a REELLEMENT envoye, nuls compris. `exclude_none`
                # ecartait les champs remis a null, or c'est precisement le geste
                # qui remet le profil a « non tranche » et qui, quelques lignes plus
                # haut, regenere toute la grille de frais de l'inscription. Le
                # journal ne gardait donc aucune trace de la seule action qui
                # explique pourquoi la dette d'une famille a change.
                #
                # `mode="json"` parce que la colonne d'audit est du JSON : un enum
                # ou une date rendus en objets Python y lèvent une erreur illisible.
                new_values=data.model_dump(include=champs, mode="json"),
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
        academic_year = await _get_current_academic_year(db)
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

        # 1. Create student
        student = Student(
            first_name=data.first_name,
            last_name=data.last_name,
            birth_date=data.birth_date,
            birth_place=data.birth_place,
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
            is_new_student=await _profil_a_retenir(db, data, student.id, academic_year_id),
        )

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
        student_name=_nom_eleve(refreshed),
        class_name=refreshed.class_.name if refreshed.class_ else "",
        acteur_id=created_by,
    )
    return _to_response(refreshed)


async def re_enroll_student(
    db: AsyncSession,
    data: ReEnrollmentCreate,
    created_by: int,
    *,
    arrears: ArrearsClearance,
) -> EnrollmentResponse:
    """Re-inscrit un eleve existant dans une nouvelle classe/annee.

    Aucun garde ici : ce chemin délègue à `create_enrollment`, qui le porte. Il
    se contente de lui transmettre ce que le routeur a résolu.
    """
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
        in_kind_deposits=data.in_kind_deposits,
    )
    return await create_enrollment(db, enrollment_data, created_by=created_by, arrears=arrears)


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
