"""Porte de paiement des documents officiels.

Un certificat, une attestation ou un bulletin sont retenus quand la famille
n'a pas verse ce qui etait **deja exigible**. Le declencheur est le retard sur
l'echeancier, jamais le solde total : en novembre, une famille parfaitement a
jour de sa premiere tranche doit pouvoir obtenir un certificat de scolarite
pour une bourse ou une carte de transport.

La direction peut deroger avec un motif obligatoire. Sans cette porte, la
premiere situation humaine legitime — cas social, bourse promise, versement
en especes pas encore saisi — pousserait quelqu'un a enregistrer un faux
paiement pour contourner, et on aurait casse la comptabilite au lieu de la
proteger.
"""

import logging
from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditAction, audit_log
from app.models.academic import AcademicYear
from app.models.enrollment import Enrollment, EnrollmentStatus
from app.models.grade import Bulletin
from app.services.installments import resolve_schedule

logger = logging.getLogger(__name__)

# Statut HTTP dedie : « il faut payer ». Distinct du 403, qui dirait « vous
# n'avez pas le droit » — le front doit pouvoir separer les deux pour afficher
# un montant et un chemin de paiement plutot qu'un refus sec.
_PAYMENT_REQUIRED = 402


@dataclass(frozen=True, slots=True)
class ReleaseStatus:
    """Le document peut-il sortir, et sinon pourquoi."""

    blocked: bool
    late_amount: float
    enrollment_id: int | None
    academic_year_name: str | None

    @property
    def reason(self) -> str | None:
        if not self.blocked:
            return None
        return (
            f"{self.late_amount:,.0f} FCFA d'échéances arrivées à terme restent impayées."
        ).replace(",", " ")


async def _current_enrollment(db: AsyncSession, student_id: int) -> tuple[int, str] | None:
    """Inscription validée de l'élève pour l'année courante."""
    stmt = (
        select(Enrollment.id, AcademicYear.name)
        .join(AcademicYear, AcademicYear.id == Enrollment.academic_year_id)
        .where(
            Enrollment.student_id == student_id,
            Enrollment.status == EnrollmentStatus.VALIDE,
            AcademicYear.is_current.is_(True),
        )
        .limit(1)
    )
    row = (await db.execute(stmt)).first()
    return (int(row[0]), str(row[1])) if row else None


async def evaluate_release(db: AsyncSession, student_id: int) -> ReleaseStatus:
    """Dit si les documents de cet élève sont retenus, et de combien.

    Un élève sans inscription validée pour l'année courante n'est pas retenu
    ici : son cas relève des règles d'inscription, pas du recouvrement. Le
    bloquer pour impayé serait un message faux.
    """
    current = await _current_enrollment(db, student_id)
    if current is None:
        return ReleaseStatus(
            blocked=False, late_amount=0.0, enrollment_id=None, academic_year_name=None
        )

    enrollment_id, year_name = current
    schedule = await resolve_schedule(db, enrollment_id)

    return ReleaseStatus(
        blocked=schedule.is_late,
        late_amount=schedule.late_amount,
        enrollment_id=enrollment_id,
        academic_year_name=year_name,
    )


async def ensure_releasable(
    db: AsyncSession,
    student_id: int,
    *,
    document_kind: str,
    actor_id: int,
    may_override: bool,
    override_reason: str | None,
) -> None:
    """Laisse passer, ou refuse en 402 avec le montant en cause.

    `may_override` vient de la permission `documents:release:override`, pas
    d'un test de rôle en dur. Une dérogation exige un motif : sans lui, le
    journal dirait qu'on a passé outre sans dire pourquoi, ce qui ne vaut
    guère mieux que pas de trace du tout.
    """
    status = await evaluate_release(db, student_id)
    if not status.blocked:
        return

    reason = (override_reason or "").strip()
    if not may_override or not reason:
        raise HTTPException(
            status_code=_PAYMENT_REQUIRED,
            detail={
                "code": "DOCUMENT_BLOCKED_BY_ARREARS",
                "message": (
                    f"Document retenu : {status.reason} "
                    "Rendez-vous au secrétariat de l'école pour régulariser."
                ),
                "late_amount": status.late_amount,
                "student_id": student_id,
                "can_override": may_override,
            },
        )

    await audit_log(
        db,
        entity_type="document_release_override",
        action=AuditAction.UPDATE,
        user_id=actor_id,
        entity_id=student_id,
        new_values={
            "document_kind": document_kind,
            "student_id": student_id,
            "enrollment_id": status.enrollment_id,
            "late_amount": status.late_amount,
            "reason": reason,
        },
        notes=reason,
    )
    await db.commit()
    logger.info(
        "Derogation document %s pour l'eleve %s par l'utilisateur %s : %s",
        document_kind,
        student_id,
        actor_id,
        reason,
    )


async def ensure_bulletin_releasable(
    db: AsyncSession,
    bulletin_id: int,
    *,
    actor_id: int,
    may_override: bool,
    override_reason: str | None,
) -> None:
    """Meme porte, pour un bulletin identifie par son id.

    Le bulletin ne porte pas le student_id dans l'URL ; on le resout ici
    plutot que dans le routeur, pour que la regle de retenue reste dans un
    seul fichier.
    """
    student_id = (
        await db.execute(select(Bulletin.student_id).where(Bulletin.id == bulletin_id))
    ).scalar_one_or_none()
    if student_id is None:
        return  # Bulletin inexistant : le service PDF levera le 404 attendu.

    await ensure_releasable(
        db,
        int(student_id),
        document_kind="bulletin",
        actor_id=actor_id,
        may_override=may_override,
        override_reason=override_reason,
    )
