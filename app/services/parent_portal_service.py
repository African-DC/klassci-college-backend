"""Service portail parent — logique métier lecture seule."""

import logging
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.models.enrollment import EnrollmentStatus
from app.models.user import Parent, ParentStudent
from app.repositories import admin_repository
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
from app.services import (
    bulletin_access,
    bulletin_document_service,
    bulletin_visibility,
    document_release_service,
    fees_paid,
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


async def build_child_summaries(db: AsyncSession, parent: Parent) -> list[ParentDashboardChild]:
    """Agrège, pour chaque enfant d'un parent, classe + moyenne + absences + reste à payer.

    Réutilisé par le dashboard parent (portail) et la réponse INFO WhatsApp
    (MailPulse). Une query par enfant — acceptable (1-3 enfants par parent).
    """
    from app.services.attendance_service import get_student_attendance_summary

    links = await repo.list_children(db, parent.id)

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

        # Reste à payer sur l'inscription active. Source de vérité : les
        # allocations, pas `EnrollmentFee.payments`, qui s'appuie sur un lien
        # déprécié depuis la migration 0028 et surestimait donc la dette
        # affichée au parent, sur l'écran d'accueil de son portail.
        fees_remaining = Decimal("0.00")
        if active is not None:
            enrollment = await repo.get_student_active_enrollment(db, student.id)
            if enrollment is not None:
                paid_by_fee = await fees_paid.paid_by_enrollment(db, enrollment.id)
                for ef in enrollment.enrollment_fees:
                    paid = paid_by_fee.get(ef.id, Decimal("0"))
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
                fees_remaining=float(fees_remaining),
            )
        )

    return summaries


async def get_dashboard(db: AsyncSession, user_id: int) -> ParentDashboardResponse:
    """Dashboard parent : pour chaque enfant, agrège classe + moyenne + absences + reste à payer."""
    parent = await _get_parent_for_user(db, user_id)
    parent_name = f"{parent.first_name} {parent.last_name}".strip()
    summaries = await build_child_summaries(db, parent)
    current_ay_name = await admin_repository.get_current_academic_year_name(db)

    return ParentDashboardResponse(
        parent_name=parent_name,
        total_children=len(summaries),
        children=summaries,
        current_academic_year=current_ay_name,
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

    # Source de verite : les allocations, pas `EnrollmentFee.payments`, qui
    # s'appuie sur un lien deprecie depuis la migration 0028 et sous-estime
    # donc ce que la famille a verse. C'est elle qui lit ce chiffre.
    paid_by_fee = await fees_paid.paid_by_enrollment(db, enrollment.id)
    # Le detail sous chaque frais vient des allocations lui aussi : la
    # relation depreciee renvoyait une liste vide, donc un frais solde sans
    # aucun versement visible en dessous.
    payments_by_fee = await fees_paid.payments_by_enrollment_fee(db, enrollment.id)

    fees: list[FeeDetail] = []
    total_due = Decimal("0.00")
    total_paid = Decimal("0.00")

    for ef in enrollment.enrollment_fees:
        total_due += ef.amount
        payments = [
            PaymentDetail(
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
    """Retourne les bulletins publiés d'un enfant, vidés de leur contenu si impayé.

    Même porte que le téléchargement, appliquée à la consultation : rendre ici
    la moyenne, le rang et la mention pendant que le PDF est retenu
    reviendrait à publier le bulletin en refusant de l'imprimer.

    Les bulletins retenus restent dans la liste. Les faire disparaître ferait
    croire au parent qu'aucun bulletin n'a été édité, et l'enverrait
    téléphoner au secrétariat pour une panne imaginaire.
    """
    parent = await _get_parent_for_user(db, user_id)
    await _verify_child_access(db, parent.id, student_id)

    bulletins = await repo.get_student_bulletins(db, student_id)

    release = await document_release_service.evaluate_release(db, student_id)
    withholding = bulletin_visibility.Withholding.from_release(release)

    bulletin_details = [
        BulletinDetail(
            **withholding.apply(
                {
                    "id": b.id,
                    "trimester": b.trimester,
                    "average": b.average,
                    "rank": b.rank,
                    "mention": b.mention,
                    "class_name": b.class_.name if b.class_ else "N/A",
                    "academic_year_name": b.academic_year.name if b.academic_year else "N/A",
                    "is_published": b.is_published,
                    "generated_at": b.generated_at,
                }
            )
        )
        for b in bulletins
    ]

    return ChildBulletinsResponse(student_id=student_id, bulletins=bulletin_details)


async def get_child_bulletin_pdf(
    db: AsyncSession, user_id: int, student_id: int, bulletin_id: int
) -> bytes:
    """Rend le PDF d'un bulletin publie d'un enfant du parent connecte.

    Le lien de filiation absent rend ici un 404 sur le bulletin, la ou les
    autres routes du portail rendent un 403 sur l'enfant. Ce n'est pas une
    incoherence : les autres routes se lisent sur une page ou le parent a
    choisi son enfant dans sa propre liste, et un 403 lui dit clairement
    « cet enfant n'est pas le votre ». Ici, l'identifiant du bulletin est un
    entier qu'on peut incrementer, et distinguer « n'existe pas » de
    « existe mais pas a vous » suffirait a cartographier les bulletins de
    l'ecole. Un seul refus, indistinct, pour les deux.

    L'appartenance passe avant la porte de paiement, qui annonce en 402 le
    montant impaye et l'identifiant de l'eleve : interrogee sur l'enfant d'une
    autre famille, elle en revelerait la situation financiere. Un parent ne
    peut pas non plus lever cette retenue : la derogation se demande au
    secretariat, qui en porte le motif au journal.
    """
    parent = await _get_parent_for_user(db, user_id)
    link = await repo.get_parent_student_link(db, parent.id, student_id)
    if link is None:
        raise NotFoundError("Bulletin", bulletin_id)

    await bulletin_access.ensure_owned_and_published(db, bulletin_id, student_id=student_id)
    await document_release_service.ensure_bulletin_releasable(
        db,
        bulletin_id,
        actor_id=user_id,
        may_override=False,
        override_reason=None,
    )
    return await bulletin_document_service.get_bulletin_pdf(db, bulletin_id)


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
