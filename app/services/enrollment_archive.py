"""Corbeille des inscriptions : archiver, restaurer, supprimer.

Extrait de `enrollment_service`. Ces trois gestes n'ont rien à voir avec le
CRUD d'une inscription : ils décident de ce qui disparaît des écrans et de ce
qui disparaît pour de bon.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.audit import AuditAction, audit_log
from app.core.exceptions import BusinessValidationError, NotFoundError
from app.models.enrollment import Enrollment, EnrollmentStatus
from app.models.fee import Payment
from app.repositories import enrollment_repository as repo
from app.services import archive_service
from app.services.archive_service import ArchiveOutcome


def _enrollment_label(record: object) -> str:
    """« L'inscription de Traoré Aminata » plutôt que « L'inscription #42 ».

    Le numéro ne dit rien à la personne qui relit le journal ou qui hésite
    devant la corbeille ; le nom de l'élève, si.
    """
    student = getattr(record, "student", None)
    if student is None:
        return f"L'inscription #{getattr(record, 'id', '')}"
    nom = f"{student.last_name} {student.first_name}".strip()
    return f"L'inscription de {nom}"


async def _load_enrollment_for_bin(db: AsyncSession, enrollment_id: int) -> Enrollment | None:
    """Charge l'inscription même archivée, avec l'élève dont on tire le libellé.

    L'élève est chargé ici, pas plus tard : après le `commit` de l'archivage,
    une relation non préchargée déclencherait une lecture paresseuse hors
    contexte async.
    """
    from app.core.archive_filter import INCLUDE_ARCHIVED

    stmt = (
        select(Enrollment)
        .where(Enrollment.id == enrollment_id)
        .options(selectinload(Enrollment.student))
        .execution_options(**{INCLUDE_ARCHIVED: True})
    )
    return (await db.execute(stmt)).scalar_one_or_none()


ENROLLMENT_KIND = archive_service.ArchivableKind(
    "enrollment",
    "L'inscription",
    Enrollment,
    lambda db, r: repo.delete_enrollment(db, r),
    naming=_enrollment_label,
    load=_load_enrollment_for_bin,
)


async def _refuse_if_money_moved(db: AsyncSession, enrollment_id: int) -> None:
    """Interdit de faire disparaître une inscription validée déjà encaissée.

    Une inscription archivée quitte tous les écrans, y compris ceux de la
    caisse : la masquer alors que des versements y sont rattachés ferait
    silencieusement mentir le bordereau du jour. La règle valait déjà pour la
    suppression, elle vaut d'abord pour l'archivage puisque c'est désormais le
    premier geste.
    """
    statut = (
        await db.execute(select(Enrollment.status).where(Enrollment.id == enrollment_id))
    ).scalar_one_or_none()
    if statut != EnrollmentStatus.VALIDE:
        return

    verses = (
        await db.execute(
            select(func.count()).select_from(Payment).where(Payment.enrollment_id == enrollment_id)
        )
    ).scalar_one()
    if verses:
        raise BusinessValidationError(
            "Cette inscription est validée et porte déjà des versements : "
            "elle ne peut pas être mise à la corbeille."
        )


async def archive_enrollment(
    db: AsyncSession, enrollment_id: int, *, reason: str | None, actor_id: int
) -> ArchiveOutcome:
    """Place l'inscription dans la corbeille : elle quitte les écrans, rien n'est détruit."""
    await _refuse_if_money_moved(db, enrollment_id)
    return await archive_service.archive_record(
        db, ENROLLMENT_KIND, enrollment_id, reason=reason, actor_id=actor_id
    )


async def restore_enrollment(db: AsyncSession, enrollment_id: int, *, actor_id: int) -> None:
    """Sort l'inscription de la corbeille."""
    await archive_service.restore_record(db, ENROLLMENT_KIND, enrollment_id, actor_id=actor_id)


async def delete_enrollment(
    db: AsyncSession,
    enrollment_id: int,
    deleted_by: int,
    reason: str | None = None,
) -> None:
    """Supprime une inscription ou lève 404. Bloque si statut valide avec paiements."""
    enrollment = await repo.get_enrollment_by_id(db, enrollment_id)
    if enrollment is None:
        raise NotFoundError("Enrollment", enrollment_id)

    # Le garde lisait `EnrollmentFee.payments`, c'est-à-dire l'ancienne
    # colonne `payments.enrollment_fee_id`, plus jamais renseignée depuis que
    # le versement se fait sur l'inscription. Il laissait donc passer toutes
    # les inscriptions payées depuis ce changement. On compte désormais les
    # versements là où ils sont réellement rattachés.
    versements = (
        await db.execute(
            select(func.count()).select_from(Payment).where(Payment.enrollment_id == enrollment_id)
        )
    ).scalar() or 0
    if versements:
        raise BusinessValidationError(
            "Impossible de supprimer une inscription qui porte des versements encaissés. "
            "Passez par la fiche de l'élève : la corbeille conserve les versements."
        )

    async with db.begin_nested():
        await repo.delete_enrollment(db, enrollment)
        await audit_log(
            db,
            entity_type="enrollment",
            action=AuditAction.DELETE,
            user_id=deleted_by,
            entity_id=enrollment_id,
        )

    await db.commit()
