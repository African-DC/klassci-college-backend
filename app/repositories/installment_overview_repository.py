"""Lectures groupées pour le suivi des échéanciers d'un établissement.

Les montants passent par les *mêmes* constructeurs de requête que
l'échéancier individuel. Ne jamais sommer Payment.amount ou recréer une
définition concurrente des frais obligatoires.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessValidationError
from app.core.names import compact
from app.models.academic import Class
from app.models.enrollment import CLOSED_STATUSES, Enrollment
from app.models.fee import EnrollmentFee
from app.models.installment import EnrollmentInstallment
from app.models.user import Student
from app.repositories import installment_repository
from app.services import fees_paid

# Le journal de paiement utilise le même plafond d'export : aucun document
# de 5001 lignes ne doit sortir tronqué sans avertissement.
COHORT_LIMIT = 5000
BATCH_SIZE = 400


@dataclass(frozen=True, slots=True)
class EnrollmentIdentity:
    enrollment_id: int
    first_name: str
    last_name: str
    matricule: str | None
    class_id: int
    class_name: str


async def list_identities(
    db: AsyncSession,
    *,
    academic_year_id: int,
    class_id: int | None = None,
    search: str = "",
) -> list[EnrollmentIdentity]:
    stmt = (
        select(
            Enrollment.id,
            Student.first_name,
            Student.last_name,
            Student.enrollment_number,
            Class.id,
            Class.name,
        )
        .join(Student, Student.id == Enrollment.student_id)
        .join(Class, Class.id == Enrollment.class_id)
        .where(
            Enrollment.academic_year_id == academic_year_id,
            Enrollment.status.notin_(CLOSED_STATUSES),
        )
        .order_by(Class.name, Student.last_name, Student.first_name, Enrollment.id)
        .limit(COHORT_LIMIT + 1)
    )
    if class_id is not None:
        stmt = stmt.where(Enrollment.class_id == class_id)
    if search.strip():
        # Les clés de recherche normalisées existent déjà sur Student :
        # pas de transformation SQL géante, ni de nouvelle vérité sur les noms.
        # `autoescape` : un « % » ou un « _ » saisi est cherché tel quel. Sans
        # lui, « % » renvoyait toute l'école et un matricule à tiret bas
        # trouvait aussi d'autres élèves.
        # La normalisation des noms peut vider le terme (« % », « - ») : une
        # chaîne vide correspondrait alors à tous les élèves.
        needle = compact(search.strip())
        raw = search.strip().lower()
        clauses = [func.lower(Student.enrollment_number).contains(raw, autoescape=True)]
        if needle:
            clauses += [
                Student.first_name_key.contains(needle, autoescape=True),
                Student.last_name_key.contains(needle, autoescape=True),
            ]
        stmt = stmt.where(or_(*clauses))

    rows = (await db.execute(stmt)).all()
    if len(rows) > COHORT_LIMIT:
        raise BusinessValidationError(
            "Plus de 5 000 inscriptions correspondent à la recherche. "
            "Choisissez une classe ou affinez la recherche avant de consulter ou d'exporter."
        )
    return [
        EnrollmentIdentity(
            enrollment_id=int(r[0]),
            first_name=r[1],
            last_name=r[2],
            matricule=r[3],
            class_id=int(r[4]),
            class_name=r[5],
        )
        for r in rows
    ]


async def mandatory_totals(db: AsyncSession, enrollment_ids: list[int]) -> dict[int, Decimal]:
    """Même assiette que `installment_repository.mandatory_total`, groupée."""
    totals: dict[int, Decimal] = {}
    for offset in range(0, len(enrollment_ids), BATCH_SIZE):
        ids = enrollment_ids[offset : offset + BATCH_SIZE]
        # Le WHERE obligatoire/exonéré vit dans _frais_dus : pas de copie.
        stmt = (
            installment_repository._frais_dus()
            .add_columns(EnrollmentFee.enrollment_id)
            .where(EnrollmentFee.enrollment_id.in_(ids))
            .group_by(EnrollmentFee.enrollment_id)
        )
        for montant, eid in (await db.execute(stmt)).all():
            totals[int(eid)] = Decimal(str(montant or 0))
    return totals


async def mandatory_paid(db: AsyncSession, enrollment_ids: list[int]) -> dict[int, Decimal]:
    """Même périmètre que `fees_paid.paid_on_mandatory`, toutes caisses."""
    paid: dict[int, Decimal] = {}
    for offset in range(0, len(enrollment_ids), BATCH_SIZE):
        ids = enrollment_ids[offset : offset + BATCH_SIZE]
        stmt = (
            fees_paid._allocations_sur_frais_dus()
            .add_columns(EnrollmentFee.enrollment_id)
            .where(EnrollmentFee.enrollment_id.in_(ids))
            .group_by(EnrollmentFee.enrollment_id)
        )
        for montant, eid in (await db.execute(stmt)).all():
            paid[int(eid)] = Decimal(str(montant or 0))
    return paid


async def negotiated_plans(
    db: AsyncSession, enrollment_ids: list[int]
) -> dict[int, list[EnrollmentInstallment]]:
    plans: dict[int, list[EnrollmentInstallment]] = {}
    for offset in range(0, len(enrollment_ids), BATCH_SIZE):
        ids = enrollment_ids[offset : offset + BATCH_SIZE]
        stmt = (
            select(EnrollmentInstallment)
            .where(EnrollmentInstallment.enrollment_id.in_(ids))
            .order_by(EnrollmentInstallment.enrollment_id, EnrollmentInstallment.position)
        )
        for row in (await db.execute(stmt)).scalars():
            plans.setdefault(int(row.enrollment_id), []).append(row)
    return plans
