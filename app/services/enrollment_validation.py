"""Valider une inscription : la transition, et ce qu'elle exige.

Une inscription se déroule en trois gestes : on ouvre le dossier, on encaisse,
on valide. « Validée » veut dire que la famille a commencé à payer. Tant que
le serveur ne le vérifiait pas, le geste se faisait dans le mauvais ordre : à
Rostan, sur trente jours de rentrée, 701 inscriptions ont été validées une
dizaine de secondes après leur création, avant tout versement. Le statut ne
disait alors plus rien de la caisse.

La règle, décidée le 2026-09-24 : pas de validation sans versement reçu. Une
inscription qui n'a rien à régler en argent (bourse, frais exonérés ou tous
déposés en nature) se valide sans versement, puisqu'il n'y a rien à attendre.

Sorti de `enrollment_service`, qui dépassait déjà la taille qu'un lecteur
tient en tête.
"""

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditAction, audit_log
from app.core.exceptions import BusinessValidationError, NotFoundError
from app.models.enrollment import Enrollment, EnrollmentStatus
from app.models.fee import EnrollmentFee, EnrollmentFeeStatus, Payment, PaymentStatus
from app.repositories import enrollment_repository as repo
from app.schemas.enrollment import EnrollmentResponse
from app.services.enrollment_mapper import to_enrollment_response

AUCUN_VERSEMENT = (
    "Aucun versement n'est enregistré sur cette inscription. "
    "Encaissez d'abord un versement, puis validez."
)


async def enrollments_with_payment(db: AsyncSession, enrollment_ids: Iterable[int]) -> set[int]:
    """Parmi ces inscriptions, celles qui ont reçu au moins un versement.

    Un versement annulé ne compte pas : l'argent est reparti. Une requête pour
    toute une page de liste, pas une par ligne.
    """
    ids = sorted(set(enrollment_ids))
    if not ids:
        return set()
    stmt = (
        select(Payment.enrollment_id)
        .where(
            Payment.enrollment_id.in_(ids),
            Payment.status == PaymentStatus.COMPLETED.value,
        )
        .distinct()
    )
    return {int(i) for i in (await db.execute(stmt)).scalars().all() if i is not None}


async def awaiting_payment(db: AsyncSession, enrollment_ids: Iterable[int]) -> set[int]:
    """Parmi ces inscriptions, celles qui attendent un versement pour être validées.

    La règle de la garde, et la seule : aucun versement reçu, ET quelque chose
    reste dû en argent. L'écran lit ce résultat tel quel pour choisir entre
    « Encaisser » et « Valider » ; s'il le recalculait de son côté, un boursier
    exonéré resterait bloqué sur « Encaisser » pour une dette nulle.

    Deux requêtes pour une page entière. Sans versement, rien n'est encore
    imputé : un frais reste dû s'il est encaissable et non nul.
    """
    ids = set(enrollment_ids)
    sans_versement = ids - await enrollments_with_payment(db, ids)
    if not sans_versement:
        return set()
    encaissables = (EnrollmentFeeStatus.PENDING.value, EnrollmentFeeStatus.PARTIAL.value)
    stmt = (
        select(EnrollmentFee.enrollment_id)
        .where(
            EnrollmentFee.enrollment_id.in_(sorted(sans_versement)),
            EnrollmentFee.status.in_(encaissables),
            EnrollmentFee.amount > 0,
        )
        .distinct()
    )
    return {int(i) for i in (await db.execute(stmt)).scalars().all()}


async def ensure_payment_received(db: AsyncSession, enrollment_id: int) -> None:
    """Refuse la validation tant que l'inscription attend un versement."""
    if enrollment_id in await awaiting_payment(db, [enrollment_id]):
        raise BusinessValidationError(AUCUN_VERSEMENT)


def verifier_statut(enrollment: Enrollment) -> None:
    """Seuls `prospect` et `en_validation` se valident, avec un refus lisible."""
    if enrollment.status == EnrollmentStatus.VALIDE:
        raise BusinessValidationError("Cette inscription est déjà validée.")
    if enrollment.status not in (EnrollmentStatus.PROSPECT, EnrollmentStatus.EN_VALIDATION):
        raise BusinessValidationError(
            f"Impossible de valider une inscription au statut « {enrollment.status.value} »."
        )


async def appliquer_validation(
    db: AsyncSession,
    enrollment: Enrollment,
    validated_by: int,
    *,
    exiger_versement: bool = True,
) -> None:
    """Vérifie et écrit la transition vers « valide », sans commit.

    Le bouton « Valider » et le formulaire d'édition passent par ici. Sans
    commit propre, l'édition peut valider ET changer de classe dans une seule
    transaction : une classe pleine annule alors les deux, au lieu de laisser
    un dossier validé derrière une erreur.
    """
    previous_status = enrollment.status
    verifier_statut(enrollment)
    if exiger_versement:
        await ensure_payment_received(db, enrollment.id)

    await repo.update_enrollment(db, enrollment, status=EnrollmentStatus.VALIDE)
    await audit_log(
        db,
        entity_type="enrollment",
        action=AuditAction.UPDATE,
        user_id=validated_by,
        entity_id=enrollment.id,
        old_values={"status": previous_status.value},
        new_values={"status": EnrollmentStatus.VALIDE.value, "transition": "validate"},
    )


async def validate_enrollment(
    db: AsyncSession,
    enrollment_id: int,
    validated_by: int,
    *,
    exiger_versement: bool = True,
) -> EnrollmentResponse:
    """Transitionne une inscription `prospect` ou `en_validation` vers `valide`.

    `exiger_versement` n'est levé que par le jeu de données de démonstration,
    qui fabrique des dossiers validés avant de passer à la caisse. Aucun
    chemin HTTP ne le transmet.
    """
    enrollment = await repo.get_enrollment_by_id(db, enrollment_id)
    if enrollment is None:
        raise NotFoundError("Enrollment", enrollment_id)
    # Avant la transaction : un refus de statut n'a rien à ouvrir ni à annuler.
    verifier_statut(enrollment)

    async with db.begin_nested():
        await appliquer_validation(db, enrollment, validated_by, exiger_versement=exiger_versement)

    await db.commit()

    refreshed = await repo.get_enrollment_by_id(db, enrollment_id)
    if refreshed is None:
        raise NotFoundError("Enrollment", enrollment_id)
    return to_enrollment_response(refreshed)


async def validate_enrollments_in_bulk(
    db: AsyncSession,
    enrollment_ids: list[int],
    validated_by: int,
) -> dict[str, object]:
    """Valide plusieurs inscriptions, et dit ce qui a échoué.

    Une inscription qui refuse la transition n'arrête pas les autres. Chaque
    échec est rendu avec son motif, en face de son identifiant : un dossier
    sans versement revient avec « Aucun versement n'est enregistré », et le
    secrétariat sait lequel envoyer à la caisse.

    Chaque validation garde son audit propre : le lot est une commodité de
    l'écran, pas une opération à part que l'historique ne saurait pas relire.
    """
    validees: list[int] = []
    echecs: list[dict[str, object]] = []

    for enrollment_id in enrollment_ids:
        try:
            await validate_enrollment(db, enrollment_id, validated_by)
            validees.append(enrollment_id)
        except (BusinessValidationError, NotFoundError) as exc:
            echecs.append({"enrollment_id": enrollment_id, "reason": str(exc.detail)})

    return {"validated": validees, "failed": echecs}
