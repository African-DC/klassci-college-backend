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
from datetime import datetime

from sqlalchemy import Select, or_, select

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


__all__ = ["PaymentFilters", "apply_payment_filters"]
