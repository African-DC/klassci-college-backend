"""Service portail eleve — logique metier read-only."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import NotFoundError
from app.models.attendance import AttendanceRecord, AttendanceStatus
from app.models.grade import Evaluation, Grade
from app.models.user import Student
from app.repositories import admin_repository
from app.repositories import student_portal_repository as repo
from app.schemas.student_portal import (
    BulletinResponse,
    EnrollmentFeeResponse,
    EvaluationDetail,
    PaymentResponse,
    StudentBulletinsListResponse,
    StudentDashboardResponse,
    StudentFeesResponse,
    StudentGradeResponse,
    StudentGradesListResponse,
    StudentLatestGrade,
    StudentNextCourse,
    StudentProfileResponse,
    StudentTimetableResponse,
    TimetableSlotResponse,
)
from app.services import (
    bulletin_access,
    bulletin_document_service,
    document_release_service,
    fees_paid,
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
    # Source de verite : les allocations, pas `EnrollmentFee.payments`, qui
    # s'appuie sur un lien deprecie depuis la migration 0028 et sous-estime
    # donc ce que la famille a verse. C'est elle qui lit ce chiffre.
    paid_by_fee = await fees_paid.paid_by_enrollment(db, enrollment.id)
    # Le detail sous chaque frais vient des allocations lui aussi : la
    # relation depreciee renvoyait une liste vide, donc un frais solde sans
    # aucun versement visible en dessous.
    payments_by_fee = await fees_paid.payments_by_enrollment_fee(db, enrollment.id)

    total_due = Decimal("0.00")
    total_paid = Decimal("0.00")
    fee_responses = []

    for ef in enrollment_fees:
        total_due += ef.amount
        payments = [
            PaymentResponse(
                id=p.id,
                # Part imputee a CE frais, pas le montant total du versement.
                amount=montant,
                method=p.method,
                status=p.status,
                reference=p.reference,
                created_at=p.created_at,
            )
            for p, montant in payments_by_fee.get(ef.id, [])
        ]
        fee_paid = paid_by_fee.get(ef.id, Decimal("0"))
        total_paid += fee_paid

        category_name = (
            ef.fee_variant.category.name if ef.fee_variant and ef.fee_variant.category else "N/A"
        )
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


async def get_bulletin_pdf(db: AsyncSession, user_id: int, bulletin_id: int) -> bytes:
    """Rend le PDF d'un bulletin publie de l'eleve connecte.

    L'ordre des trois controles compte. L'appartenance passe avant la porte de
    paiement : celle-ci repond 402 en annoncant le montant reste impaye et
    l'identifiant de l'eleve concerne. Interrogee sur le bulletin d'un
    camarade, elle revelerait donc a la fois son existence et la situation
    financiere de sa famille.

    La famille ne peut jamais lever la retenue pour impaye : la derogation se
    demande au secretariat, qui porte un motif au journal. Sans cette porte
    ici, une famille retenue au guichet obtiendrait le document en ouvrant son
    propre portail, et la retenue ne serait plus qu'un decor.
    """
    student = await _get_student_for_user(db, user_id)
    await bulletin_access.ensure_owned_and_published(db, bulletin_id, student_id=student.id)
    await document_release_service.ensure_bulletin_releasable(
        db,
        bulletin_id,
        actor_id=user_id,
        may_override=False,
        override_reason=None,
    )
    return await bulletin_document_service.get_bulletin_pdf(db, bulletin_id)


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


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


_DAY_INDEX_TO_NAME = {
    0: "lundi",
    1: "mardi",
    2: "mercredi",
    3: "jeudi",
    4: "vendredi",
    5: "samedi",
    6: "dimanche",
}


async def _next_course_for_class(db: AsyncSession, class_id: int) -> StudentNextCourse | None:
    """Retourne le prochain créneau dans la semaine pour une classe."""
    slots = await repo.get_timetable_slots_for_class(db, class_id)
    if not slots:
        return None

    now = datetime.now()
    today = _DAY_INDEX_TO_NAME.get(now.weekday())
    current_time = now.time()

    candidates = [s for s in slots if s.day == today and s.start_time > current_time]
    candidates.sort(key=lambda s: s.start_time)

    chosen = candidates[0] if candidates else slots[0]  # fallback : 1er slot semaine
    teacher_name = ""
    if chosen.teacher:
        teacher_name = f"{chosen.teacher.first_name} {chosen.teacher.last_name}".strip()

    return StudentNextCourse(
        subject_name=chosen.subject.name if chosen.subject else "",
        teacher_name=teacher_name,
        start_time=chosen.start_time.strftime("%H:%M"),
        end_time=chosen.end_time.strftime("%H:%M"),
        room=chosen.room.name if chosen.room else None,
    )


async def get_dashboard(db: AsyncSession, user_id: int) -> StudentDashboardResponse:
    """Compose le dashboard de l'élève à partir des sources existantes.

    Aligné sur le contrat FE `StudentDashboardSchema`
    (lib/contracts/student-portal.ts) : nom, classe, prochain cours,
    moyenne générale du trimestre courant, frais restants, total absences.
    """
    student = await _get_student_for_user(db, user_id)
    enrollment = await repo.get_active_enrollment_for_student(db, student.id)

    class_name = enrollment.class_.name if enrollment else "—"
    class_id = enrollment.class_id if enrollment else None

    # Prochain cours
    next_course = await _next_course_for_class(db, class_id) if class_id else None

    # Moyenne générale (toutes notes saisies, tous trimestres confondus pour
    # garder l'usage simple à l'écran d'accueil).
    avg_stmt = select(func.avg(Grade.value)).where(
        Grade.student_id == student.id, Grade.value.is_not(None)
    )
    avg_raw = (await db.execute(avg_stmt)).scalar()
    general_average = round(float(avg_raw), 2) if avg_raw is not None else None

    # Dernière note saisie : mise en avant sur l'accueil (l'élève voit tout de
    # suite son résultat le plus récent). Tri par date d'évaluation décroissante.
    latest_stmt = (
        select(Grade)
        .join(Evaluation, Evaluation.id == Grade.evaluation_id)
        .where(Grade.student_id == student.id, Grade.value.is_not(None))
        .options(selectinload(Grade.evaluation).selectinload(Evaluation.subject))
        .order_by(Evaluation.date.desc(), Grade.id.desc())
        .limit(1)
    )
    latest_row = (await db.execute(latest_stmt)).scalars().first()
    latest_grade = None
    if latest_row is not None and latest_row.evaluation is not None:
        ev = latest_row.evaluation
        latest_grade = StudentLatestGrade(
            value=float(latest_row.value) if latest_row.value is not None else 0.0,
            out_of=20,
            subject_name=ev.subject.name if ev.subject else "",
            evaluation_title=ev.title,
            type=ev.type,
            trimester=ev.trimester,
            date=ev.date,
        )

    # Reste à payer. Source de vérité : les allocations, pas
    # `EnrollmentFee.payments`, qui s'appuie sur un lien déprécié depuis la
    # migration 0028 et surestimait donc la dette annoncée à l'élève dès sa
    # page d'accueil.
    fees_remaining = Decimal("0")
    if enrollment:
        fees = await repo.get_enrollment_fees_for_enrollment(db, enrollment.id)
        paid_by_fee = await fees_paid.paid_by_enrollment(db, enrollment.id)
        for fee in fees:
            paid = paid_by_fee.get(fee.id, Decimal("0"))
            balance = fee.amount - paid
            if balance > 0:
                fees_remaining += balance

    # Total absences
    abs_stmt = (
        select(func.count())
        .select_from(AttendanceRecord)
        .where(
            AttendanceRecord.student_id == student.id,
            AttendanceRecord.status == AttendanceStatus.ABSENT,
        )
    )
    total_absences = (await db.execute(abs_stmt)).scalar() or 0

    current_ay_name = await admin_repository.get_current_academic_year_name(db)

    return StudentDashboardResponse(
        student_name=f"{student.first_name} {student.last_name}".strip(),
        class_name=class_name,
        next_course=next_course,
        general_average=general_average,
        latest_grade=latest_grade,
        fees_remaining=float(fees_remaining),
        total_absences=int(total_absences),
        current_academic_year=current_ay_name,
    )
