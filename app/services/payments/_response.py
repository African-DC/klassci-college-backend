"""Builders Pydantic pour les responses Payment / PaymentAllocation.

Les builders prennent un ORM `Payment` déjà chargé avec toutes ses
relations (cf. `repo.get_payment_with_allocations`). Aucun fetch DB ici —
juste de la projection.
"""

from app.models.fee import Payment, PaymentAllocation
from app.schemas.payment import PaymentAllocationResponse, PaymentResponse


def allocation_to_response(allocation: PaymentAllocation) -> PaymentAllocationResponse:
    """Sérialise un PaymentAllocation avec sa catégorie."""
    fee_category_name = None
    fee_category_priority = None
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

    return PaymentAllocationResponse(
        id=allocation.id,
        enrollment_fee_id=allocation.enrollment_fee_id,
        amount=allocation.amount,
        fee_category_name=fee_category_name,
        fee_category_priority=fee_category_priority,
        enrollment_fee_status_after=enrollment_fee_status_after,
    )


def payment_to_response(payment: Payment) -> PaymentResponse:
    """Convertit un Payment ORM en PaymentResponse avec champs enrichis."""
    student_name = None
    student_photo_url = None
    fee_name = None

    enrollment = getattr(payment, "enrollment", None)
    if enrollment is not None:
        student = getattr(enrollment, "student", None)
        if student is not None:
            student_name = f"{student.first_name} {student.last_name}"
            student_photo_url = getattr(student, "photo_url", None)

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
        allocations=[allocation_to_response(a) for a in allocations],
    )
