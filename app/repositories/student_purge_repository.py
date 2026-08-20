"""Suppression définitive d'un élève — ce qui part, et ce qui reste.

Une seule règle décide de tout ici : **l'argent encaissé ne s'efface pas.**

La caissière avait compté ces billets. Le tiroir était juste ce soir-là, le
point journalier a été signé, le bordereau est classé. Supprimer les
versements d'un élève ferait mentir tous ces documents d'un coup, sans que
personne ne s'en aperçoive avant le prochain contrôle. Alors l'inscription
part, les frais partent, les notes et les présences partent, mais les
versements restent : détachés de l'inscription, et portant désormais le nom
et le matricule figés de celui qui a payé.

Le reste de ce fichier n'est que la conséquence de cette règle. L'ordre des
suppressions suit les clés étrangères de bas en haut ; c'est ce qui évite de
buter sur un `RESTRICT` au milieu du travail, une fiche à moitié détruite.
"""

from sqlalchemy import ColumnElement, func, select, update
from sqlalchemy import delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.attachment import StudentDocument
from app.models.attendance import AttendanceRecord
from app.models.enrollment import Document, Enrollment, StudentOption
from app.models.fee import EnrollmentFee, Payment, PaymentAllocation
from app.models.grade import Bulletin, CouncilStudentDecision, Grade, SubjectAverage
from app.models.installment import EnrollmentInstallment
from app.models.user import ParentStudent, Student
from app.services.deletion import Dependent


def student_display_name(student: Student) -> str:
    """Nom figé recopié sur les versements. Jamais vide : c'est ce qui restera."""
    parts = [(student.last_name or "").strip(), (student.first_name or "").strip()]
    return " ".join(p for p in parts if p) or f"Élève {student.id}"


async def _enrollment_ids(db: AsyncSession, student_id: int) -> list[int]:
    stmt = select(Enrollment.id).where(Enrollment.student_id == student_id)
    return list((await db.execute(stmt)).scalars())


async def freeze_student_identity_on_payments(
    db: AsyncSession, student: Student, *, enrollment_ids: list[int] | None = None
) -> int:
    """Recopie nom et matricule sur les versements de l'élève. Retourne le compte.

    Appelée dès la mise à la corbeille, pas seulement à la suppression : le
    filtre qui masque les fiches archivées masque aussi l'élève derrière le
    versement, et un bordereau journalier dont la colonne « Élève » se vide
    du jour au lendemain n'est plus un document comptable.

    Idempotente : réécrire la même valeur ne coûte rien et rattrape les
    versements enregistrés avant l'arrivée de ces colonnes.
    """
    if enrollment_ids is None:
        enrollment_ids = await _enrollment_ids(db, student.id)
    if not enrollment_ids:
        return 0

    result = await db.execute(
        update(Payment)
        .where(Payment.enrollment_id.in_(enrollment_ids))
        .values(
            student_name_snapshot=student_display_name(student),
            student_matricule_snapshot=student.enrollment_number,
        )
    )
    await db.flush()
    return int(result.rowcount or 0)


async def _count(db: AsyncSession, model: type, condition: ColumnElement[bool]) -> int:
    """Compte avant de supprimer. `ParentStudent` n'ayant pas de colonne `id`,
    on compte les lignes plutôt qu'une clé primaire simple."""
    stmt = select(func.count()).select_from(model).where(condition)
    return int((await db.execute(stmt)).scalar() or 0)


async def purge_student_keeping_payments(
    db: AsyncSession, student: Student
) -> tuple[Dependent, ...]:
    """Détruit la fiche élève et tout ce qui en dépend, sauf les versements.

    Retourne l'inventaire de ce qui a été emporté, pour le journal d'audit et
    pour le courriel envoyé à la direction : « supprimé » sans dire quoi ne
    vaut guère mieux que pas de trace.
    """
    enrollment_ids = await _enrollment_ids(db, student.id)

    # 1. Figer l'identité AVANT toute destruction. Une fois la fiche partie,
    #    on ne peut plus relire le nom qu'on aurait dû recopier.
    payments_kept = await freeze_student_identity_on_payments(
        db, student, enrollment_ids=enrollment_ids
    )

    inventaire: list[Dependent] = []

    if enrollment_ids:
        fee_ids = list(
            (
                await db.execute(
                    select(EnrollmentFee.id).where(EnrollmentFee.enrollment_id.in_(enrollment_ids))
                )
            ).scalars()
        )

        # 2. Détacher les versements de l'inscription. C'est le geste qui les
        #    fait survivre : la clé étrangère est en RESTRICT, elle refuserait
        #    la suppression de l'inscription tant qu'un versement y pend.
        await db.execute(
            update(Payment)
            .where(Payment.enrollment_id.in_(enrollment_ids))
            .values(enrollment_id=None, enrollment_fee_id=None)
        )

        # 3. Les répartitions par frais disparaissent avec les frais : elles
        #    désignent une dette qui n'existe plus. Le versement, lui, garde
        #    son montant total — c'est la seule somme qui compte pour la caisse.
        if fee_ids:
            await db.execute(
                sa_delete(PaymentAllocation).where(PaymentAllocation.enrollment_fee_id.in_(fee_ids))
            )
            await db.execute(sa_delete(EnrollmentFee).where(EnrollmentFee.id.in_(fee_ids)))
            inventaire.append(Dependent("frais d'élève", "frais d'élève", len(fee_ids)))

        for model, singulier, pluriel in (
            (EnrollmentInstallment, "échéance", "échéances"),
            (StudentOption, "option choisie", "options choisies"),
            (Document, "pièce justificative", "pièces justificatives"),
        ):
            count = await _count(db, model, model.enrollment_id.in_(enrollment_ids))
            if count:
                await db.execute(sa_delete(model).where(model.enrollment_id.in_(enrollment_ids)))
                inventaire.append(Dependent(singulier, pluriel, count))

    # 4. Vie scolaire et résultats. Tous en RESTRICT sur l'élève : sans ces
    #    suppressions, la base refuserait la dernière ligne.
    for model, singulier, pluriel in (
        (Grade, "note", "notes"),
        (SubjectAverage, "moyenne par matière", "moyennes par matière"),
        (Bulletin, "bulletin", "bulletins"),
        (CouncilStudentDecision, "décision de conseil", "décisions de conseil"),
        (AttendanceRecord, "présence relevée", "présences relevées"),
        (StudentDocument, "document déposé", "documents déposés"),
        (ParentStudent, "lien avec un parent", "liens avec des parents"),
    ):
        count = await _count(db, model, model.student_id == student.id)
        if count:
            await db.execute(sa_delete(model).where(model.student_id == student.id))
            inventaire.append(Dependent(singulier, pluriel, count))

    if enrollment_ids:
        await db.execute(sa_delete(Enrollment).where(Enrollment.id.in_(enrollment_ids)))
        inventaire.insert(0, Dependent("inscription", "inscriptions", len(enrollment_ids)))

    # Suppression en bloc plutôt que `db.delete(student)` : l'ORM voudrait
    # d'abord recharger `Student.enrollments`, `.grades`, `.parents` pour
    # détacher des enfants qu'on vient précisément d'effacer, et ce
    # rechargement échoue hors contexte async.
    await db.execute(sa_delete(Student).where(Student.id == student.id))
    await db.flush()
    db.expunge(student)

    if payments_kept:
        # Signalé comme le reste, mais c'est l'inverse d'une perte : le
        # courriel doit dire noir sur blanc que l'argent, lui, est resté.
        inventaire.append(
            Dependent(
                "versement conservé (détaché de l'inscription)",
                "versements conservés (détachés de l'inscription)",
                payments_kept,
            )
        )

    return tuple(inventaire)
