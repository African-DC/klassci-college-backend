"""Repository paiements — accès DB pour Payment, PaymentAllocation, EnrollmentFee.

Architecture (refactor 2026-05-17) :
- La source de vérité du "montant payé sur un fee" est `payment_allocations`
  (somme des splits sur les paiements completed). L'ancien chemin par
  `payments.enrollment_fee_id` reste pour les vieilles rows mais ne doit
  plus être écrit.
- Les nouveaux paiements passent par `record_enrollment_payment` qui crée
  Payment + N PaymentAllocation en transaction.
"""

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.enrollment import Enrollment
from app.models.fee import (
    EnrollmentFee,
    FeeCategory,
    FeeVariant,
    Payment,
    PaymentAllocation,
)
from app.repositories.payment_filters import PaymentFilters, apply_payment_filters

# ---------------------------------------------------------------------------
# Loaders communs (selectinload exhaustif — voir preload-relations-after-commit)
# ---------------------------------------------------------------------------


def _payment_full_options():
    """Tout ce que le service / le PDF / la notif consomment post-commit."""
    from app.models.user import Student, User

    return (
        # Pour le notif dispatch
        selectinload(Payment.enrollment)
        .selectinload(Enrollment.student)
        .selectinload(Student.user),
        # Pour l'en-tete du recu, qui nomme la classe et l'annee. Sans elles,
        # le `getattr` du service declenche un chargement paresseux hors
        # contexte : MissingGreenlet, et la famille repart sans son recu.
        selectinload(Payment.enrollment).selectinload(Enrollment.class_),
        selectinload(Payment.enrollment).selectinload(Enrollment.academic_year),
        # Pour les allocations enrichies dans la response
        selectinload(Payment.allocations)
        .selectinload(PaymentAllocation.enrollment_fee)
        .selectinload(EnrollmentFee.fee_variant)
        .selectinload(FeeVariant.category),
        # Pour l'ancien champ `fee_name` (rétrocompat response)
        selectinload(Payment.enrollment_fee)
        .selectinload(EnrollmentFee.fee_variant)
        .selectinload(FeeVariant.category),
        # Pour nommer l'encaisseur. Les deux profils sont chargés parce qu'un
        # versement peut avoir ete encaisse par un poste administratif comme
        # par un enseignant regisseur : lire le mauvais profil rendrait une
        # colonne vide sur un document comptable.
        selectinload(Payment.received_by_user).selectinload(User.staff_profile),
        selectinload(Payment.received_by_user).selectinload(User.teacher_profile),
        # L'annulateur se lit sur la ligne annulee, au meme titre que
        # l'encaisseur : sans lui, « annule par » resterait vide.
        selectinload(Payment.cancelled_by_user).selectinload(User.staff_profile),
        selectinload(Payment.cancelled_by_user).selectinload(User.teacher_profile),
    )


# ---------------------------------------------------------------------------
# Payment getters
# ---------------------------------------------------------------------------


async def get_payment_by_id(db: AsyncSession, payment_id: int) -> Payment | None:
    """Retourne un paiement par ID avec toutes les relations consommées.

    Inclut maintenant `allocations` (avec category) + `enrollment.student.user`.
    """
    stmt = select(Payment).where(Payment.id == payment_id).options(*_payment_full_options())
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_payment_with_allocations(db: AsyncSession, payment_id: int) -> Payment | None:
    """Alias explicite — même chargement que `get_payment_by_id`."""
    return await get_payment_by_id(db, payment_id)


async def list_payments(
    db: AsyncSession,
    *,
    filters: PaymentFilters,
    page: int = 1,
    size: int = 20,
) -> tuple[list[Payment], int]:
    """Retourne une page de paiements avec le total.

    Les critères arrivent composés : l'écran et les deux exports passent le
    même objet, donc un filtre ajouté vaut pour les trois. Les recopier ici
    en paramètres separés avait déjà laissé la recherche et la catégorie hors
    de la requête, acceptées par l'API et silencieusement ignorées.

    `filters.received_by` cloisonne un caissier sur sa propre caisse. Il est
    appliqué dans la requête, pas après coup sur la page : filtrer en Python
    laisserait le total et la pagination compter les versements des collègues,
    et le caissier verrait « 128 versements » en n'en lisant que les siens.
    """
    base = apply_payment_filters(
        select(Payment).options(*_payment_full_options()),
        filters,
    )

    count_stmt = select(func.count()).select_from(base.subquery())
    total: int = (await db.execute(count_stmt)).scalar() or 0

    stmt = base.offset((page - 1) * size).limit(size).order_by(Payment.id.desc())
    rows = (await db.execute(stmt)).scalars().all()
    return list(rows), total


async def get_payments_by_enrollment_id(db: AsyncSession, enrollment_id: int) -> list[Payment]:
    """Retourne tous les paiements d'une inscription (via Payment.enrollment_id)."""
    stmt = (
        select(Payment)
        .where(Payment.enrollment_id == enrollment_id)
        .options(*_payment_full_options())
        .order_by(Payment.id.desc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# EnrollmentFee getters
# ---------------------------------------------------------------------------


async def get_enrollment_fee_by_id(
    db: AsyncSession, enrollment_fee_id: int
) -> EnrollmentFee | None:
    """Retourne un EnrollmentFee par ID."""
    stmt = select(EnrollmentFee).where(EnrollmentFee.id == enrollment_fee_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_enrollment_fee_for_update(
    db: AsyncSession, enrollment_fee_id: int
) -> EnrollmentFee | None:
    """Retourne un EnrollmentFee avec verrou FOR UPDATE (race condition guard)."""
    stmt = select(EnrollmentFee).where(EnrollmentFee.id == enrollment_fee_id).with_for_update()
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_enrollment_fees_ordered_by_priority(
    db: AsyncSession, enrollment_id: int, *, lock: bool
) -> list[EnrollmentFee]:
    """Tous les frais d'une inscription, triés par priorité de catégorie ASC.

    Priorité basse d'abord : Inscription, puis Tenue, puis le reste. Rend
    aussi les frais soldés, exonérés et déposés en nature. C'est ce qui permet
    de distinguer un frais déjà réglé d'un frais qui n'appartient pas à cette
    inscription, sans payer une requête de plus pour le dire ; le tri de ce
    qui peut encore recevoir de l'argent se fait ensuite, en mémoire.

    `lock` n'a pas de valeur par défaut, et c'est délibéré. Cette fonction
    sert deux chemins aux besoins opposés : l'aperçu, qui lit pendant que le
    caissier tape et ne doit rien verrouiller, et l'encaissement, qui écrit et
    doit tenir les lignes jusqu'au commit. Le dépôt a déjà perdu ce verrou une
    fois, en remplaçant une requête verrouillante par une requête d'aperçu qui
    lui ressemblait : les deux ne diffèrent plus que par ce mot, et il est
    obligatoire à l'appel.

    Avec `lock=True`, le `FOR UPDATE` ne porte que sur `EnrollmentFee` : les
    catégories et les variantes ne sont jointes que pour trier, les verrouiller
    sérialiserait tous les encaissements de l'établissement entre eux.
    """
    stmt = (
        select(EnrollmentFee)
        .join(FeeVariant, EnrollmentFee.fee_variant_id == FeeVariant.id)
        .join(FeeCategory, FeeVariant.fee_category_id == FeeCategory.id)
        .where(EnrollmentFee.enrollment_id == enrollment_id)
        .options(
            selectinload(EnrollmentFee.fee_variant).selectinload(FeeVariant.category),
        )
        .order_by(FeeCategory.priority.asc(), EnrollmentFee.id.asc())
    )
    if lock:
        stmt = stmt.with_for_update(of=EnrollmentFee)
    result = await db.execute(stmt)
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Combien a été versé sur un frais : voir `app.services.fees_paid`.
#
# La formule vivait ici une seconde fois, frais par frais. Quatre boucles
# l'appelaient, dont celle de la caisse : encaisser sur une inscription à six
# frais coûtait six requêtes séquentielles là où `fees_paid.paid_by_enrollment`
# en fait une seule, groupée. Deux copies d'un même calcul finissent par
# diverger, et c'est de l'argent qu'elles comptent.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Enrollment loader (avec FOR UPDATE pour la transaction de paiement)
# ---------------------------------------------------------------------------


async def get_enrollment_for_update(db: AsyncSession, enrollment_id: int) -> Enrollment | None:
    """Verrouille l'inscription le temps du calcul de l'allocation."""
    from app.models.user import Student

    stmt = (
        select(Enrollment)
        .where(Enrollment.id == enrollment_id)
        .options(
            selectinload(Enrollment.student).selectinload(Student.user),
        )
        .with_for_update(of=Enrollment)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Payment / Allocation writers
# ---------------------------------------------------------------------------


async def create_payment(
    db: AsyncSession,
    *,
    enrollment_id: int,
    amount: Decimal,
    method: str,
    status: str,
    reference: str | None,
    received_by: int | None,
    notes: str | None,
    enrollment_fee_id: int | None = None,
) -> Payment:
    """Crée un Payment (acte caissier) et le flush pour obtenir l'ID.

    `enrollment_fee_id` reste accepté pour le path legacy (rétrocompat
    POST /payments) — sinon NULL.
    """
    payment = Payment(
        enrollment_id=enrollment_id,
        enrollment_fee_id=enrollment_fee_id,
        amount=amount,
        method=method,
        status=status,
        reference=reference,
        received_by=received_by,
        notes=notes,
    )
    db.add(payment)
    await db.flush()
    return payment


async def create_allocation(
    db: AsyncSession,
    *,
    payment_id: int,
    enrollment_fee_id: int,
    amount: Decimal,
) -> PaymentAllocation:
    """Crée un split PaymentAllocation."""
    allocation = PaymentAllocation(
        payment_id=payment_id,
        enrollment_fee_id=enrollment_fee_id,
        amount=amount,
    )
    db.add(allocation)
    await db.flush()
    return allocation


async def get_allocations_for_payment(db: AsyncSession, payment_id: int) -> list[PaymentAllocation]:
    """Toutes les allocations d'un Payment, avec category pour l'audit."""
    stmt = (
        select(PaymentAllocation)
        .where(PaymentAllocation.payment_id == payment_id)
        .options(
            selectinload(PaymentAllocation.enrollment_fee)
            .selectinload(EnrollmentFee.fee_variant)
            .selectinload(FeeVariant.category),
        )
        .order_by(PaymentAllocation.id.asc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())
