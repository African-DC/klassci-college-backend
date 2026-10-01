"""Service inscriptions — création, lecture, modification, réinscription.

La corbeille vit dans `enrollment_archive`, les frais dans `enrollment_fees`,
l'inscription couplée élève + inscription dans `enrollment_with_student`, les
options facultatives dans `enrollment_options` : ce fichier portait cinq sujets
sans rapport, et plus personne ne le relisait en entier.
"""

import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditAction, audit_log
from app.core.exceptions import BusinessValidationError, NotFoundError, PermissionDeniedError
from app.models.enrollment import EnrollmentStatus
from app.repositories import enrollment_repository as repo
from app.schemas.enrollment import (
    EnrollmentCreate,
    EnrollmentListResponse,
    EnrollmentResponse,
    EnrollmentUpdate,
    ReEnrollmentCreate,
)
from app.schemas.enrollment_profile import PROFILE_FIELDS
from app.services import (
    enrollment_arrears,
    enrollment_fees,
    enrollment_profile,
    enrollment_validation,
)
from app.services import enrollment_creation_steps as steps

# Réexporté : la cloche de la caisse sonne désormais depuis
# `enrollment_creation_steps`, mais les tests la remplacent par ce chemin-ci.
# C'est le même module, donc le même remplacement.
from app.services import enrollment_notifications as enrollment_notifications
from app.services.enrollment_arrears import ArrearsClearance
from app.services.enrollment_mapper import to_enrollment_response as _to_response

# Réexportée : l'inscription couplée vit dans son module, mais le seed de démo
# et les tests l'appellent encore par ce nom-ci.
from app.services.enrollment_with_student import create_enrollment_with_student

__all__ = [
    "create_enrollment",
    "create_enrollment_with_student",
    "get_enrollment",
    "list_enrollments",
    "re_enroll_student",
    "update_enrollment",
]

logger = logging.getLogger(__name__)

_VALID_STATUSES = {s.value for s in EnrollmentStatus}
#: Filtre d'écran « À valider » : prospect + en_validation, la queue du jour.
_FILTRE_STATUTS = _VALID_STATUSES | {"a_valider"}


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
    academic_year = await steps.resolve_academic_year(db, data.academic_year_id)

    # Porte de paiement — AVANT la transaction, et ce n'est pas un détail : le
    # garde n'a pas le droit de commettre au milieu d'un `begin_nested()`, il
    # validerait la moitié d'une inscription. Il lit, et laisse sa ligne de
    # journal au commit de `finish_creation`.
    await enrollment_arrears.ensure_enrollable(
        db,
        student_id=data.student_id,
        year=academic_year,
        actor_id=created_by,
        clearance=arrears,
    )

    # Tout dans une seule transaction, classe verrouillée (FOR UPDATE) contre
    # les inscriptions concurrentes.
    async with db.begin_nested():
        await steps.ensure_class_has_room(db, data.class_id, data.academic_year_id)
        await _ensure_no_active_enrollment(db, data.student_id, data.academic_year_id)
        enrollment = await steps.insert_enrollment(
            db, data, student_id=data.student_id, year=academic_year, created_by=created_by
        )
        await steps.attach_fees(
            db,
            enrollment,
            fee_variant_id=data.fee_variant_id,
            in_kind_deposits=data.in_kind_deposits,
            created_by=created_by,
        )
        await steps.audit_creation(
            db, enrollment, data.model_dump(mode="json"), created_by=created_by
        )

    return await steps.finish_creation(db, enrollment.id, created_by=created_by)


async def _ensure_no_active_enrollment(
    db: AsyncSession, student_id: int, academic_year_id: int
) -> None:
    """Garde doublon, dans la transaction : une inscription vivante par élève et par année."""
    existing = await repo.get_active_enrollment(db, student_id, academic_year_id)
    if existing is not None:
        raise BusinessValidationError(
            f"Student {student_id} already has an active enrollment for this academic year"
        )


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
    plan = _plan_edit(enrollment, data, peut_valider=peut_valider)

    async with db.begin_nested():
        if plan.class_changed:
            await steps.ensure_class_has_room(db, data.class_id, enrollment.academic_year_id)
        await _write_edit(db, enrollment, data, plan)

        # Régénérer les frais obligatoires si la classe, le profil ou
        # l'affectation a changé : chacun décide du tarif appliqué.
        if plan.regenerates_fees:
            await enrollment_fees.regenerate_enrollment_fees(
                db, enrollment_id, regenerated_by=updated_by
            )
        if plan.class_changed:
            await enrollment_profile.clear_lv2_if_class_forbids_it(db, enrollment, actor=updated_by)

        # Après la régénération : la garde de versement lit la grille de frais
        # que l'inscription aura réellement, pas celle d'avant la modification.
        if plan.validation:
            await enrollment_validation.appliquer_validation(db, enrollment, updated_by)

        if plan.champs:
            await _audit_edit(db, enrollment_id, data, plan, updated_by)

    await db.commit()

    refreshed = await repo.get_enrollment_by_id(db, enrollment_id)
    if refreshed is None:
        raise NotFoundError("Enrollment", enrollment_id)
    return _to_response(refreshed)


@dataclass(frozen=True, slots=True)
class _EditPlan:
    """Ce qu'une édition touche, décidé avant toute écriture."""

    #: Passer à « valide » est une validation, qui passe par la sienne.
    validation: bool
    #: Les champs à journaliser : le statut n'y est pas s'il valide.
    champs: frozenset[str]
    old_values: dict[str, Any]
    class_changed: bool
    profil_envoye: bool
    affectation_envoyee: bool
    decision_envoyee: bool
    regenerates_fees: bool


def _plan_edit(enrollment: Any, data: EnrollmentUpdate, *, peut_valider: bool) -> _EditPlan:
    """Lit ce que le client a réellement envoyé, `None` compris.

    `None` est une valeur ici, pas une absence : corriger le profil doit
    rejouer la grille, sinon la case change et la facture reste celle de
    l'autre profil. D'où `model_fields_set` et non un test sur la valeur.
    """
    validation = (
        data.status == EnrollmentStatus.VALIDE.value
        and enrollment.status != EnrollmentStatus.VALIDE
    )
    if validation and not peut_valider:
        raise PermissionDeniedError("enrollments:validate")
    sent = data.model_fields_set
    class_changed = data.class_id is not None and data.class_id != enrollment.class_id
    profil_envoye = "is_new_student" in sent
    affectation_envoyee = "assignment_status" in sent
    profil_change = profil_envoye and data.is_new_student != enrollment.is_new_student
    affectation_change = (
        affectation_envoyee and data.assignment_status != enrollment.assignment_status
    )
    return _EditPlan(
        validation=validation,
        champs=frozenset(sent - ({"status"} if validation else set())),
        old_values={name: getattr(enrollment, name) for name in _EDIT_AUDITED},
        class_changed=class_changed,
        profil_envoye=profil_envoye,
        affectation_envoyee=affectation_envoyee,
        decision_envoyee="assignment_decision_number" in sent,
        regenerates_fees=class_changed or profil_change or affectation_change,
    )


#: L'état d'avant que le journal d'une édition garde.
_EDIT_AUDITED = (
    "status",
    "notes",
    "class_id",
    "is_new_student",
    "assignment_status",
    "assignment_decision_number",
)


async def _write_edit(
    db: AsyncSession, enrollment: Any, data: EnrollmentUpdate, plan: _EditPlan
) -> None:
    """Écrit les champs envoyés ; un champ absent reste intact (`repo.UNSET`)."""
    await repo.update_enrollment(
        db,
        enrollment,
        status=None if plan.validation else data.status,
        notes=data.notes,
        class_id=data.class_id,
        is_new_student=(data.is_new_student if plan.profil_envoye else repo.UNSET),
        assignment_status=(data.assignment_status if plan.affectation_envoyee else repo.UNSET),
        assignment_decision_number=(
            data.assignment_decision_number if plan.decision_envoyee else repo.UNSET
        ),
    )


async def _audit_edit(
    db: AsyncSession, enrollment_id: int, data: EnrollmentUpdate, plan: _EditPlan, actor: int
) -> None:
    """Journalise ce que le client a REELLEMENT envoyé, nuls compris.

    `exclude_none` écartait les champs remis à null, or c'est précisément le
    geste qui remet le profil à « non tranché » et régénère toute la grille de
    frais : le journal ne gardait aucune trace de la seule action qui explique
    pourquoi la dette d'une famille a changé. `mode="json"` parce que la
    colonne d'audit est du JSON.
    """
    await audit_log(
        db,
        entity_type="enrollment",
        action=AuditAction.UPDATE,
        user_id=actor,
        entity_id=enrollment_id,
        old_values=plan.old_values,
        new_values=data.model_dump(include=set(plan.champs), mode="json"),
    )


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
    academic_year_id = (await steps.resolve_academic_year(db, data.academic_year_id)).id

    # Use existing create_enrollment logic (handles capacity + duplicate guard)
    enrollment_data = EnrollmentCreate(
        student_id=data.student_id,
        class_id=data.class_id,
        academic_year_id=academic_year_id,
        fee_variant_id=data.fee_variant_id,
        notes=data.notes,
        in_kind_deposits=data.in_kind_deposits,
        **data.model_dump(include=set(PROFILE_FIELDS)),
    )
    return await create_enrollment(db, enrollment_data, created_by=created_by, arrears=arrears)
