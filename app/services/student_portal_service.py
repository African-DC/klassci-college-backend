"""Service portail eleve — logique metier read-only."""

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.fee import PaymentStatus
from app.models.user import Student
from app.repositories import student_portal_repository as repo
from app.schemas.student_portal import (
    BulletinResponse,
    EnrollmentFeeResponse,
    EvaluationDetail,
    PaymentResponse,
    StudentBulletinsListResponse,
    StudentFeesResponse,
    StudentGradeResponse,
    StudentGradesListResponse,
    StudentProfileResponse,
    StudentTimetableResponse,
    TimetableSlotResponse,
)


async def _get_student_for_user(db: AsyncSession, user_id: int) -> Student:
    """Retourne le profil eleve ou leve 404."""
    student = await repo.get_student_by_user_id(db, user_id)
    if student is None:
        raise NotFoundError("Student profile not found for this user", user_id)
    return student


async def get_grades(
    db: AsyncSession,
    user_id: int,
    *,
    trimester: int | None = None,
    subject_id: int | None = None,
) -> StudentGradesListResponse:
    """Retourne les notes de l'eleve connecte."""
    student = await _get_student_for_user(db, user_id)
    grades = await repo.get_grades_for_student(
        db, student.id, trimester=trimester, subject_id=subject_id
    )

    items = [
        StudentGradeResponse(
            id=g.id,
            value=g.value,
            status=g.status,
            evaluation=EvaluationDetail(
                id=g.evaluation.id,
                title=g.evaluation.title,
                type=g.evaluation.type,
                date=g.evaluation.date,
                coefficient=g.evaluation.coefficient,
                trimester=g.evaluation.trimester,
                subject_name=g.evaluation.subject.name,
            ),
        )
        for g in grades
    ]
    return StudentGradesListResponse(items=items, total=len(items))


async def get_timetable(db: AsyncSession, user_id: int) -> StudentTimetableResponse:
    """Retourne l'emploi du temps de la classe de l'eleve."""
    student = await _get_student_for_user(db, user_id)
    enrollment = await repo.get_active_enrollment_for_student(db, student.id)
    if enrollment is None:
        raise NotFoundError("Active enrollment not found for student", student.id)

    slots = await repo.get_timetable_slots_for_class(db, enrollment.class_id)

    slot_responses = [
        TimetableSlotResponse(
            id=s.id,
            day=s.day,
            start_time=s.start_time,
            end_time=s.end_time,
            subject_name=s.subject.name,
            teacher_name=f"{s.teacher.first_name} {s.teacher.last_name}",
            room_name=s.room.name if s.room else None,
        )
        for s in slots
    ]
    return StudentTimetableResponse(
        class_name=enrollment.class_.name,
        slots=slot_responses,
    )


async def get_fees(db: AsyncSession, user_id: int) -> StudentFeesResponse:
    """Retourne les frais et paiements de l'eleve."""
    student = await _get_student_for_user(db, user_id)
    enrollment = await repo.get_active_enrollment_for_student(db, student.id)
    if enrollment is None:
        raise NotFoundError("Active enrollment not found for student", student.id)

    enrollment_fees = await repo.get_enrollment_fees_for_enrollment(db, enrollment.id)

    total_due = Decimal("0.00")
    total_paid = Decimal("0.00")
    fee_responses = []

    for ef in enrollment_fees:
        total_due += ef.amount
        payments = [
            PaymentResponse(
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

        category_name = ef.fee_variant.category.name if ef.fee_variant and ef.fee_variant.category else "N/A"
        fee_responses.append(
            EnrollmentFeeResponse(
                id=ef.id,
                fee_category_name=category_name,
                amount=ef.amount,
                status=ef.status,
                payments=payments,
            )
        )

    return StudentFeesResponse(
        total_due=total_due,
        total_paid=total_paid,
        balance=total_due - total_paid,
        fees=fee_responses,
    )


async def get_bulletins(db: AsyncSession, user_id: int) -> StudentBulletinsListResponse:
    """Retourne les bulletins publies de l'eleve."""
    student = await _get_student_for_user(db, user_id)
    bulletins = await repo.get_published_bulletins_for_student(db, student.id)

    items = [
        BulletinResponse(
            id=b.id,
            trimester=b.trimester,
            average=b.average,
            rank=b.rank,
            mention=b.mention,
            class_name=b.class_.name,
            academic_year_name=b.academic_year.name,
            file_url=b.file_url,
            generated_at=b.generated_at,
        )
        for b in bulletins
    ]
    return StudentBulletinsListResponse(items=items, total=len(items))


async def get_profile(db: AsyncSession, user_id: int) -> StudentProfileResponse:
    """Retourne le profil complet de l'eleve."""
    student = await _get_student_for_user(db, user_id)
    enrollment = await repo.get_active_enrollment_for_student(db, student.id)

    # Recuperer l'email depuis le user lie
    email: str | None = None
    if student.user:
        email = student.user.email

    class_name: str | None = None
    class_id: int | None = None
    enrollment_status: str | None = None
    academic_year_name: str | None = None

    if enrollment:
        class_name = enrollment.class_.name
        class_id = enrollment.class_id
        enrollment_status = enrollment.status
        academic_year_name = enrollment.academic_year.name

    return StudentProfileResponse(
        id=student.id,
        first_name=student.first_name,
        last_name=student.last_name,
        birth_date=student.birth_date,
        genre=student.genre,
        enrollment_number=student.enrollment_number,
        email=email,
        class_name=class_name,
        class_id=class_id,
        enrollment_status=enrollment_status,
        academic_year_name=academic_year_name,
    )
