"""Les étapes qu'une création d'inscription enchaîne, quel que soit le guichet.

`create_enrollment` (élève existant) et `create_enrollment_with_student`
(élève saisi dans le même geste) font la même chose autour de la ligne
d'inscription : vérifier la place dans la classe, poser les frais, journaliser,
puis, une fois commis, relire et prévenir la caisse. Ces gestes vivaient en
double, chacun dans une fonction de cent lignes ; ils vivent ici une fois.
"""

from collections.abc import Sequence
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditAction, audit_log
from app.core.exceptions import BusinessValidationError, NotFoundError
from app.models.academic import AcademicYear, Class
from app.models.enrollment import Enrollment
from app.repositories import enrollment_repository as repo
from app.schemas.enrollment import (
    EnrollmentCreate,
    EnrollmentResponse,
    EnrollmentWithStudentCreate,
    InKindDeposit,
)
from app.services import enrollment_fees, enrollment_notifications, enrollment_profile
from app.services.enrollment_creation_helpers import (
    get_current_academic_year,
    nom_eleve,
    profil_a_retenir,
)
from app.services.enrollment_mapper import to_enrollment_response


async def resolve_academic_year(db: AsyncSession, academic_year_id: int | None) -> AcademicYear:
    """L'année demandée, ou l'année courante quand le corps n'en nomme pas."""
    if academic_year_id is None:
        return await get_current_academic_year(db)
    year = await repo.get_academic_year_by_id(db, academic_year_id)
    if year is None:
        raise BusinessValidationError(f"AcademicYear {academic_year_id} not found")
    return year


async def ensure_class_has_room(db: AsyncSession, class_id: int, academic_year_id: int) -> Class:
    """Verrouille la classe (FOR UPDATE) et refuse si elle est pleine pour l'année."""
    class_ = await repo.get_class_by_id_for_update(db, class_id)
    if class_ is None:
        raise BusinessValidationError(f"Class {class_id} not found")
    enrolled_count = await repo.count_active_enrollments_for_class(db, class_id, academic_year_id)
    if enrolled_count >= class_.max_students:
        raise BusinessValidationError(
            f"Class {class_id} is full ({class_.max_students} students max)"
        )
    return class_


async def insert_enrollment(
    db: AsyncSession,
    data: EnrollmentCreate | EnrollmentWithStudentCreate,
    *,
    student_id: int,
    year: AcademicYear,
    created_by: int,
) -> Enrollment:
    """La ligne d'inscription, son profil tarifaire et sa fiche de renseignements."""
    enrollment = await repo.create_enrollment(
        db,
        student_id=student_id,
        class_id=data.class_id,
        academic_year_id=year.id,
        created_by=created_by,
        notes=data.notes,
        assignment_status=data.assignment_status,
        assignment_decision_number=data.assignment_decision_number,
        is_new_student=await profil_a_retenir(db, data, student_id, year.id),
    )
    await enrollment_profile.apply_initial_profile(db, enrollment, data, year)
    return enrollment


async def attach_fees(
    db: AsyncSession,
    enrollment: Enrollment,
    *,
    fee_variant_id: int | None,
    in_kind_deposits: Sequence[InKindDeposit],
    created_by: int,
) -> None:
    """Pose les frais de l'inscription : tarif nommé, obligatoires, dépôts en nature.

    Le tarif nommé par le client (rétrocompat) passe par le garde de
    `enrollment_fees` : il doit viser cette inscription, profil compris.
    """
    if fee_variant_id is not None:
        await enrollment_fees.create_explicit_enrollment_fee(
            db, enrollment=enrollment, fee_variant_id=fee_variant_id
        )
    await enrollment_fees.create_mandatory_enrollment_fees(
        db,
        enrollment.id,
        enrollment.class_id,
        enrollment.academic_year_id,
        enrollment.assignment_status,
        enrollment.is_new_student,
    )
    await enrollment_fees.apply_in_kind_deposits(
        db, enrollment.id, in_kind_deposits, deposited_by=created_by
    )


async def audit_creation(
    db: AsyncSession, enrollment: Enrollment, values: dict[str, Any], *, created_by: int
) -> None:
    """Journalise la création avec la fiche FINALE, complétée par la réinscription.

    Le journal doit dire ce qui a été enregistré, pas seulement ce qui a été tapé.
    """
    await audit_log(
        db,
        entity_type="enrollment",
        action=AuditAction.CREATE,
        user_id=created_by,
        entity_id=enrollment.id,
        new_values={**values, **enrollment_profile.profile_values(enrollment)},
    )


async def finish_creation(
    db: AsyncSession, enrollment_id: int, *, created_by: int
) -> EnrollmentResponse:
    """Commit, relecture complète, puis la caisse est prévenue.

    Après le commit : le dossier existe, quel que soit le sort de la cloche.
    Les deux guichets passent par ici, sans quoi l'un d'eux resterait muet.
    """
    await db.commit()
    refreshed = await repo.get_enrollment_by_id(db, enrollment_id)
    if refreshed is None:
        raise NotFoundError("Enrollment", enrollment_id)
    await enrollment_notifications.prevenir_qu_il_faut_encaisser(
        db,
        enrollment_id=refreshed.id,
        student_name=nom_eleve(refreshed),
        class_name=refreshed.class_.name if refreshed.class_ else "",
        acteur_id=created_by,
    )
    return to_enrollment_response(refreshed)
