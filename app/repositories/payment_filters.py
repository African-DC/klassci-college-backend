"""Filtres de sélection des versements — une seule écriture pour tous les lecteurs.

L'écran des versements, son export PDF et son export Excel doivent montrer
exactement le même ensemble de lignes. Trois requêtes écrites séparément
finissent par diverger : un filtre ajouté d'un côté et pas de l'autre, et le
document sorti pour la comptabilité ne dit plus ce que la caissière a sous les
yeux. Les critères vivent donc ici, et les trois chemins les appliquent.

Le cloisonnement du caissier (`received_by`) est un critère comme les autres —
et c'est délibéré : appliqué dans la requête, il tient dans la liste comme dans
les exports, sans qu'on ait à y repenser à chaque nouveau lecteur.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta

from sqlalchemy import Select, and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.academic import AcademicYear
from app.models.enrollment import Enrollment
from app.models.fee import EnrollmentFee, FeeVariant, Payment, PaymentAllocation
from app.models.user import Student


@dataclass(frozen=True, slots=True)
class PaymentFilters:
    """Les critères de sélection d'un journal de versements.

    `received_by` n'est pas une préférence d'affichage : c'est la caisse dont
    l'appelant a le droit de lire les lignes. Il est résolu en amont par
    `app.services.payments.scope`, jamais recopié tel quel depuis la requête.
    """

    status: str | None = None
    method: str | None = None
    enrollment_fee_id: int | None = None
    enrollment_id: int | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    received_by: int | None = None
    #: Texte libre saisi dans la barre de recherche de l'ecran.
    search: str | None = None
    #: Categorie de frais, atteinte par les allocations du versement.
    fee_category_id: int | None = None
    #: Annee scolaire de l'inscription creditee. Sans elle, le journal
    #: melange les encaissements de toutes les annees et le collecté gonfle.
    academic_year_id: int | None = None


def apply_payment_filters[S: Select](stmt: S, filters: PaymentFilters) -> S:
    """Ajoute les clauses WHERE correspondant aux critères renseignés."""
    if filters.received_by is not None:
        stmt = stmt.where(Payment.received_by == filters.received_by)
    if filters.status is not None:
        stmt = stmt.where(Payment.status == filters.status)
    if filters.method is not None:
        stmt = stmt.where(Payment.method == filters.method)
    if filters.enrollment_id is not None:
        stmt = stmt.where(Payment.enrollment_id == filters.enrollment_id)
    if filters.enrollment_fee_id is not None:
        # Le rattachement à un frais passe par les allocations : depuis le
        # refactor 2026-05-17, `payments.enrollment_fee_id` n'est plus écrit.
        stmt = stmt.where(
            Payment.id.in_(
                select(PaymentAllocation.payment_id).where(
                    PaymentAllocation.enrollment_fee_id == filters.enrollment_fee_id
                )
            )
        )
    if filters.fee_category_id is not None:
        # Meme chemin que `enrollment_fee_id`, un cran plus haut : allocation,
        # frais, variante, categorie. `payments.enrollment_fee_id` est
        # deprecie depuis 2026-05-17 et ne sert pas de raccourci.
        stmt = stmt.where(
            Payment.id.in_(
                select(PaymentAllocation.payment_id)
                .join(EnrollmentFee, PaymentAllocation.enrollment_fee_id == EnrollmentFee.id)
                .join(FeeVariant, EnrollmentFee.fee_variant_id == FeeVariant.id)
                .where(FeeVariant.fee_category_id == filters.fee_category_id)
            )
        )
    if filters.search:
        # Le nom fige sur le versement compte autant que le nom vivant : c'est
        # le seul moyen de retrouver un encaissement dont la fiche eleve a ete
        # supprimee, et c'est precisement ce qu'une caisse doit pouvoir faire.
        motif = f"%{filters.search.strip()}%"
        stmt = stmt.where(
            or_(
                Payment.student_name_snapshot.ilike(motif),
                Payment.student_matricule_snapshot.ilike(motif),
                Payment.reference.ilike(motif),
                Payment.enrollment_id.in_(
                    select(Enrollment.id)
                    .join(Student, Enrollment.student_id == Student.id)
                    .where(
                        or_(
                            Student.first_name.ilike(motif),
                            Student.last_name.ilike(motif),
                            Student.enrollment_number.ilike(motif),
                        )
                    )
                ),
            )
        )
    if filters.date_from is not None:
        stmt = stmt.where(Payment.created_at >= filters.date_from)
    if filters.date_to is not None:
        stmt = stmt.where(Payment.created_at <= filters.date_to)
    return stmt


async def belongs_to_year(db: AsyncSession, academic_year_id: int):
    """Condition « ce versement relève de cette année scolaire ».

    Une jointure interne sur l'inscription ferait disparaître des totaux tout
    versement dont l'élève a été supprimé : le tableau de bord annoncerait
    moins d'argent encaissé que le bordereau de caisse du même jour, et
    personne ne saurait lequel croire.

    On rattache donc le versement orphelin par sa date. C'est exact : une
    somme encaissée le 12 novembre relève de l'année scolaire qui couvre le
    12 novembre, que la fiche élève existe encore ou non.

    Le rattachement à l'inscription passe par une sous-requête, pas une
    jointure : la liste, le bandeau et l'export peuvent alors partager ce
    prédicat sans se marcher sur un `JOIN enrollments` déjà posé ailleurs.
    """
    dates = (
        await db.execute(
            select(AcademicYear.start_date, AcademicYear.end_date).where(
                AcademicYear.id == academic_year_id
            )
        )
    ).one_or_none()

    par_inscription = Payment.enrollment_id.in_(
        select(Enrollment.id).where(Enrollment.academic_year_id == academic_year_id)
    )
    if dates is None:
        return par_inscription

    start = datetime.combine(dates.start_date, time.min)
    # Borne haute exclusive au lendemain de la fin : un versement encaissé à
    # 16 h le dernier jour ne doit pas tomber hors de l'année.
    end = datetime.combine(dates.end_date, time.min) + timedelta(days=1)
    return or_(
        par_inscription,
        and_(
            Payment.enrollment_id.is_(None), Payment.created_at >= start, Payment.created_at < end
        ),
    )


async def apply_payment_scope[S: Select](db: AsyncSession, stmt: S, filters: PaymentFilters) -> S:
    """Les critères d'écran, plus l'année quand elle est posée.

    L'année n'est pas un filtre comme les autres : sans elle, le journal
    additionne des exercices. Elle vit pourtant dans le même objet, pour que
    liste, bandeau et export ne puissent pas en avoir deux lectures.
    """
    stmt = apply_payment_filters(stmt, filters)
    if filters.academic_year_id is not None:
        stmt = stmt.where(await belongs_to_year(db, filters.academic_year_id))
    return stmt


__all__ = [
    "PaymentFilters",
    "apply_payment_filters",
    "apply_payment_scope",
    "belongs_to_year",
]
