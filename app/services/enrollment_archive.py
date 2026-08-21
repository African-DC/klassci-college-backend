"""Ce qui distingue une inscription des autres fiches de la corbeille.

Archiver, restaurer et supprimer définitivement obéissent partout aux mêmes
règles, et `archive_service` les applique déjà : motif obligatoire avant toute
écriture, passage par la corbeille avant toute destruction, journal d'audit
avec l'identité figée de l'auteur, courriel à la direction.

Ce module ne porte donc plus les trois gestes — il porterait alors une seconde
copie de ces règles, et c'est exactement ce qui était arrivé : la suppression
définitive d'une inscription ignorait le motif, ne vérifiait pas le passage par
la corbeille et ne prévenait personne. Il ne reste ici que ce qui est propre à
l'inscription : comment on la nomme, comment on la charge une fois masquée, et
l'argent qui interdit de la faire disparaître.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import BusinessValidationError
from app.models.archivable import ArchivableMixin
from app.models.enrollment import Enrollment, EnrollmentStatus
from app.models.fee import Payment
from app.repositories import enrollment_repository as repo
from app.services import archive_service


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


async def _count_payments(db: AsyncSession, enrollment_id: int) -> int:
    """Nombre de versements rattachés à l'inscription, quel qu'en soit le statut.

    On compte sur `Payment.enrollment_id` : depuis la migration 0028, c'est là
    que le versement se rattache. L'ancien garde lisait `EnrollmentFee.payments`,
    c'est-à-dire la colonne `payments.enrollment_fee_id` que plus personne ne
    renseigne — il laissait donc passer toutes les inscriptions payées.
    """
    stmt = select(func.count()).select_from(Payment).where(Payment.enrollment_id == enrollment_id)
    return (await db.execute(stmt)).scalar() or 0


async def _refuse_if_money_moved(db: AsyncSession, record: ArchivableMixin) -> None:
    """Interdit de faire disparaître des écrans une inscription déjà encaissée.

    Une inscription archivée quitte tous les écrans, y compris ceux de la
    caisse : la masquer alors que des versements y sont rattachés ferait
    silencieusement mentir le bordereau du jour.

    Le garde ne vise que les inscriptions validées : un prospect abandonné n'a
    rien encaissé, et c'est précisément la fiche qu'un secrétariat range.
    """
    if getattr(record, "status", None) != EnrollmentStatus.VALIDE:
        return
    if await _count_payments(db, record.id):
        raise BusinessValidationError(
            "Cette inscription est validée et porte déjà des versements : "
            "elle ne peut pas être mise à la corbeille."
        )


async def _purge_enrollment(db: AsyncSession, record: ArchivableMixin) -> None:
    """Détruit l'inscription — sauf si de l'argent y est encore rattaché.

    Plus strict que le garde de l'archivage, et volontairement : archiver se
    défait, détruire non. Un versement dont l'inscription part perdrait sa
    contrepartie quel que soit le statut de celle-ci.

    La règle vit ici, dans le `delete` du type, plutôt que dans un second
    chemin de suppression : c'est la seule chose que l'inscription ajoute au
    geste commun, elle n'a jamais justifié d'en réécrire toutes les étapes.
    """
    if await _count_payments(db, record.id):
        raise BusinessValidationError(
            "Impossible de supprimer une inscription qui porte des versements encaissés. "
            "Passez par la fiche de l'élève : la corbeille conserve les versements."
        )
    await repo.delete_enrollment(db, record)


ENROLLMENT_KIND = archive_service.ArchivableKind(
    "enrollment",
    "L'inscription",
    Enrollment,
    _purge_enrollment,
    naming=_enrollment_label,
    load=_load_enrollment_for_bin,
    before_archive=_refuse_if_money_moved,
)
