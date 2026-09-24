"""Une inscription telle que l'API la rend.

Seul point de conversion ORM vers réponse. Il vivait dans `enrollment_service`,
que `enrollment_validation` importait en retour : deux modules qui dépendaient
l'un de l'autre, pour une fonction qui ne dépend d'aucun des deux.
"""

from app.models.enrollment import Enrollment
from app.schemas.enrollment import EnrollmentResponse


def to_enrollment_response(
    enrollment: Enrollment, *, awaiting_payment: bool | None = None
) -> EnrollmentResponse:
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
        assignment_status=enrollment.assignment_status,
        assignment_decision_number=enrollment.assignment_decision_number,
        is_new_student=enrollment.is_new_student,
        awaiting_payment=awaiting_payment,
    )
