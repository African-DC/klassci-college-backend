"""Builders Pydantic pour les responses Payment / PaymentAllocation.

Les builders prennent un ORM `Payment` déjà chargé avec toutes ses
relations (cf. `repo.get_payment_with_allocations`). Aucun fetch DB ici —
juste de la projection.
"""

from app.models.fee import Payment, PaymentAllocation
from app.schemas.fee import FeeEntitlement
from app.schemas.payment import PaymentAllocationResponse, PaymentResponse
from app.services import fee_entitlements as entitlements


def allocation_to_response(allocation: PaymentAllocation) -> PaymentAllocationResponse:
    """Sérialise un PaymentAllocation avec sa catégorie."""
    fee_category_name = None
    fee_category_priority = None
    fee_category_entitlements: list[FeeEntitlement] = []
    enrollment_fee_status_after = None
    ef = getattr(allocation, "enrollment_fee", None)
    if ef is not None:
        enrollment_fee_status_after = ef.status
        fv = getattr(ef, "fee_variant", None)
        if fv is not None:
            cat = getattr(fv, "category", None)
            if cat is not None:
                fee_category_name = cat.name
                fee_category_priority = cat.priority
                fee_category_entitlements = entitlements.read(cat)

    return PaymentAllocationResponse(
        id=allocation.id,
        enrollment_fee_id=allocation.enrollment_fee_id,
        amount=allocation.amount,
        fee_category_name=fee_category_name,
        fee_category_entitlements=fee_category_entitlements,
        fee_category_priority=fee_category_priority,
        enrollment_fee_status_after=enrollment_fee_status_after,
    )


def student_identity(payment: Payment) -> tuple[str | None, str | None, str | None, bool]:
    """Nom, matricule, photo, et « la fiche a disparu ».

    L'inscription d'abord, l'identité figée ensuite. L'ordre compte : tant que
    l'élève existe, on affiche son nom actuel, qui peut avoir été corrigé
    depuis le versement. Une fois la fiche partie, le nom recopié est tout ce
    qui reste — et il vaut infiniment mieux qu'une case vide sur un bordereau
    de caisse.
    """
    enrollment = getattr(payment, "enrollment", None)
    student = getattr(enrollment, "student", None) if enrollment is not None else None
    if student is not None:
        return (
            f"{student.first_name} {student.last_name}",
            getattr(student, "enrollment_number", None),
            getattr(student, "photo_url", None),
            False,
        )

    fige = getattr(payment, "student_name_snapshot", None)
    matricule = getattr(payment, "student_matricule_snapshot", None)
    # Deux absences distinctes, qu'on ne confond pas : plus d'inscription du
    # tout, c'est une fiche détruite ; une inscription encore référencée mais
    # invisible, c'est une fiche dans la corbeille, qui peut revenir.
    supprime = payment.enrollment_id is None
    # Sans nom figé non plus, on nomme quand même la ligne : « None » à
    # l'écran d'une caissière ne veut rien dire, « Élève supprimé » si.
    defaut = "Élève supprimé" if supprime else "Élève archivé"
    return (fige or defaut, matricule, None, supprime)


def payment_to_response(payment: Payment) -> PaymentResponse:
    """Convertit un Payment ORM en PaymentResponse avec champs enrichis."""
    fee_name = None
    student_name, student_matricule, student_photo_url, student_deleted = student_identity(payment)

    # Legacy fee_name : si l'ancien champ existe, on l'utilise. Sinon
    # on prend la 1re allocation comme libellé indicatif.
    ef = getattr(payment, "enrollment_fee", None)
    if ef is not None:
        fv = getattr(ef, "fee_variant", None)
        if fv is not None:
            cat = getattr(fv, "category", None)
            if cat is not None:
                fee_name = cat.name

    allocations = list(getattr(payment, "allocations", []) or [])
    if fee_name is None and allocations:
        first_ef = getattr(allocations[0], "enrollment_fee", None)
        if first_ef is not None:
            fv = getattr(first_ef, "fee_variant", None)
            if fv is not None:
                cat = getattr(fv, "category", None)
                if cat is not None:
                    fee_name = cat.name

    return PaymentResponse(
        id=payment.id,
        enrollment_id=payment.enrollment_id,
        enrollment_fee_id=payment.enrollment_fee_id,
        amount=payment.amount,
        method=payment.method,
        status=payment.status,
        reference=payment.reference,
        received_by=payment.received_by,
        notes=payment.notes,
        created_at=payment.created_at,
        updated_at=payment.updated_at,
        student_name=student_name,
        student_photo_url=student_photo_url,
        fee_name=fee_name,
        student_matricule=student_matricule,
        student_deleted=student_deleted,
        allocations=[allocation_to_response(a) for a in allocations],
    )
