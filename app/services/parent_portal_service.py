"""Service portail parent — logique métier lecture seule."""

import logging
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.models.enrollment import EnrollmentStatus
from app.models.fee import PaymentStatus
from app.models.user import Parent, ParentStudent
from app.repositories import parent_portal_repository as repo
from app.schemas.parent_portal import (
    BulletinDetail,
    ChildBulletinsResponse,
    ChildEnrollmentInfo,
    ChildFeesResponse,
    ChildGradesResponse,
    ChildrenListResponse,
    ChildResponse,
    ChildTimetableResponse,
    ChildTimetableSlot,
    FeeDetail,
    GradeDetail,
    ParentDashboardChild,
    ParentDashboardResponse,
    PaymentDetail,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers internes
# ---------------------------------------------------------------------------


async def _get_parent_for_user(db: AsyncSession, user_id: int) -> Parent:
    """Récupère le profil parent ou lève NotFoundError."""
    parent = await repo.get_parent_by_user_id(db, user_id)
    if parent is None:
        raise NotFoundError("Parent", user_id)
    return parent


async def _verify_child_access(db: AsyncSession, parent_id: int, student_id: int) -> ParentStudent:
    """Vérifie que l'enfant appartient au parent ou lève PermissionDeniedError."""
    link = await repo.get_parent_student_link(db, parent_id, student_id)
    if link is None:
        raise PermissionDeniedError("access to this student")
    return link


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


async def list_children(db: AsyncSession, user_id: int) -> ChildrenListResponse:
    """Liste les enfants du parent avec leur inscription active."""
    parent = await _get_parent_for_user(db, user_id)
    links = await repo.list_children(db, parent.id)

    children: list[ChildResponse] = []
    for link in links:
        student = link.student
        enrollment_info: ChildEnrollmentInfo | None = None

        # Trouver l'inscription active la plus récente
        active_enrollments = [
            e
            for e in student.enrollments
            if e.status not in (EnrollmentStatus.ANNULE, EnrollmentStatus.REJETE)
        ]
        if active_enrollments:
            active = max(active_enrollments, key=lambda e: e.id)
            enrollment_info = ChildEnrollmentInfo(
                enrollment_id=active.id,
                class_id=active.class_id,
                class_name=active.class_.name if active.class_ else str(active.class_id),
                academic_year_name=(
                    active.academic_year.name
                    if active.academic_year
                    else str(active.academic_year_id)
                ),
                status=active.status,
            )

        children.append(
            ChildResponse(
                id=student.id,
                first_name=student.first_name,
                last_name=student.last_name,
                birth_date=student.birth_date,
                enrollment_number=student.enrollment_number,
                relationship_type=link.relationship_type,
                enrollment=enrollment_info,
            )
        )

    return ChildrenListResponse(children=children)


async def get_dashboard(db: AsyncSession, user_id: int) -> ParentDashboardResponse:
    """Dashboard parent : pour chaque enfant, agrège classe + moyenne + absences + reste à payer.

    Réutilise les helpers existants (frais, attendance) plutôt que de
    dupliquer la logique. Une query par enfant sur grades / fees / attendance
    — acceptable pour la cardinalité typique (1-3 enfants par parent).
    """
    from app.services.attendance_service import get_student_attendance_summary

    parent = await _get_parent_for_user(db, user_id)
    links = await repo.list_children(db, parent.id)
    parent_name = f"{parent.first_name} {parent.last_name}".strip()

    summaries: list[ParentDashboardChild] = []
    for link in links:
        student = link.student
        full_name = f"{student.last_name} {student.first_name}".strip()

        active_enrollments = [
            e
            for e in student.enrollments
            if e.status not in (EnrollmentStatus.ANNULE, EnrollmentStatus.REJETE)
        ]
        active = max(active_enrollments, key=lambda e: e.id) if active_enrollments else None
        class_name = active.class_.name if active and active.class_ else "—"
        ay_id = active.academic_year_id if active else None

        # General average — moyenne arithmétique simple des notes valides.
        # MVP : on n'applique pas les coefficients (la matière les porte) ;
        # le bulletin officiel utilise déjà la formule pondérée. Ici c'est
        # un indicateur global pour le résumé parent, pas un bulletin.
        grades = await repo.get_student_grades(db, student.id)
        valid_values = [
            float(g.value) for g in grades if g.value is not None and g.evaluation is not None
        ]
        general_average = round(sum(valid_values) / len(valid_values), 2) if valid_values else None

        # Total absences sur l'année active.
        if ay_id is not None:
            summary = await get_student_attendance_summary(db, student.id, academic_year_id=ay_id)
            total_absences = int(summary.get("absent", 0)) + int(summary.get("absent_excuse", 0))
        else:
            total_absences = 0

        # Fees remaining — sum (amount - completed payments) sur l'inscription active.
        fees_remaining = Decimal("0.00")
        if active is not None:
            enrollment = await repo.get_student_active_enrollment(db, student.id)
            if enrollment is not None:
                for ef in enrollment.enrollment_fees:
                    paid = sum(
                        (p.amount for p in ef.payments if p.status == PaymentStatus.COMPLETED),
                        Decimal("0.00"),
                    )
                    remaining = ef.amount - paid
                    if remaining > 0:
                        fees_remaining += remaining

        summaries.append(
            ParentDashboardChild(
                id=student.id,
                full_name=full_name,
                class_name=class_name,
                general_average=general_average,
                total_absences=total_absences,
                fees_remaining=fees_remaining,
            )
        )

    return ParentDashboardResponse(
        parent_name=parent_name,
        total_children=len(summaries),
        children=summaries,
    )


async def get_child_grades(
    db: AsyncSession, user_id: int, student_id: int, trimester: int | None = None
) -> ChildGradesResponse:
    """Retourne les notes d'un enfant."""
    parent = await _get_parent_for_user(db, user_id)
    await _verify_child_access(db, parent.id, student_id)

    grades = await repo.get_student_grades(db, student_id, trimester=trimester)

    grade_details = [
        GradeDetail(
            id=g.id,
            value=g.value,
            status=g.status,
            evaluation_title=g.evaluation.title,
            evaluation_type=g.evaluation.type,
            evaluation_date=g.evaluation.date,
            subject_name=g.evaluation.subject.name if g.evaluation.subject else "N/A",
            coefficient=g.evaluation.coefficient,
            trimester=g.evaluation.trimester,
        )
        for g in grades
    ]

    return ChildGradesResponse(student_id=student_id, grades=grade_details)


async def get_child_fees(db: AsyncSession, user_id: int, student_id: int) -> ChildFeesResponse:
    """Retourne les frais d'un enfant pour son inscription active."""
    parent = await _get_parent_for_user(db, user_id)
    await _verify_child_access(db, parent.id, student_id)

    enrollment = await repo.get_student_active_enrollment(db, student_id)

    if enrollment is None:
        return ChildFeesResponse(
            student_id=student_id,
            enrollment_id=None,
            fees=[],
            total_due=Decimal("0.00"),
            total_paid=Decimal("0.00"),
        )

    fees: list[FeeDetail] = []
    total_due = Decimal("0.00")
    total_paid = Decimal("0.00")

    for ef in enrollment.enrollment_fees:
        total_due += ef.amount
        payments = [
            PaymentDetail(
                id=p.id,
                amount=p.amount,
                method=p.method,
                status=p.status,
                reference=p.reference,
                created_at=p.created_at,
            )
            for p in ef.payments
        ]
        for p in ef.payments:
            if p.status == PaymentStatus.COMPLETED:
                total_paid += p.amount

        category_name = (
            ef.fee_variant.category.name if ef.fee_variant and ef.fee_variant.category else "N/A"
        )
        fees.append(
            FeeDetail(
                id=ef.id,
                amount=ef.amount,
                status=ef.status,
                category_name=category_name,
                payments=payments,
            )
        )

    return ChildFeesResponse(
        student_id=student_id,
        enrollment_id=enrollment.id,
        fees=fees,
        total_due=total_due,
        total_paid=total_paid,
    )


async def get_child_bulletins(
    db: AsyncSession, user_id: int, student_id: int
) -> ChildBulletinsResponse:
    """Retourne les bulletins publiés d'un enfant."""
    parent = await _get_parent_for_user(db, user_id)
    await _verify_child_access(db, parent.id, student_id)

    bulletins = await repo.get_student_bulletins(db, student_id)

    bulletin_details = [
        BulletinDetail(
            id=b.id,
            trimester=b.trimester,
            average=b.average,
            rank=b.rank,
            mention=b.mention,
            class_name=b.class_.name if b.class_ else "N/A",
            academic_year_name=b.academic_year.name if b.academic_year else "N/A",
            is_published=b.is_published,
            generated_at=b.generated_at,
        )
        for b in bulletins
    ]

    return ChildBulletinsResponse(student_id=student_id, bulletins=bulletin_details)


async def get_child_timetable(
    db: AsyncSession, user_id: int, student_id: int
) -> ChildTimetableResponse:
    """Retourne l'emploi du temps de la classe d'un enfant."""
    parent = await _get_parent_for_user(db, user_id)
    await _verify_child_access(db, parent.id, student_id)

    enrollment = await repo.get_student_active_enrollment(db, student_id)
    if enrollment is None:
        raise NotFoundError("Active enrollment not found for student", student_id)

    from app.repositories import student_portal_repository as student_repo

    slots = await student_repo.get_timetable_slots_for_class(db, enrollment.class_id)

    slot_responses = [
        ChildTimetableSlot(
            id=s.id,
            day=s.day,
            start_time=s.start_time.strftime("%H:%M")
            if hasattr(s.start_time, "strftime")
            else str(s.start_time),
            end_time=s.end_time.strftime("%H:%M")
            if hasattr(s.end_time, "strftime")
            else str(s.end_time),
            subject_name=s.subject.name if s.subject else "",
            teacher_name=f"{s.teacher.first_name} {s.teacher.last_name}" if s.teacher else "",
            room_name=s.room.name if s.room else None,
        )
        for s in slots
    ]

    class_name = enrollment.class_.name if enrollment.class_ else f"Classe #{enrollment.class_id}"
    return ChildTimetableResponse(
        student_id=student_id,
        class_name=class_name,
        slots=slot_responses,
    )
