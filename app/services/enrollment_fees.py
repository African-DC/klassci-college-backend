"""Frais d'une inscription : quel tarif s'applique, et comment il devient une dette.

Extrait de `enrollment_service`, qui portait cinq sujets sans rapport. La
résolution des tarifs est celle qu'on veut pouvoir relire — et éprouver — sans
traverser le CRUD des inscriptions : c'est elle qui décide du montant qu'une
famille verra sur sa facture.

Règle unique de ce module : **une catégorie de frais ne produit qu'une seule
ligne**. La Scolarité T1 est due une fois, quel que soit le nombre de tarifs
que l'école a saisis pour elle.
"""

from collections.abc import Iterable, Sequence
from datetime import datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.audit import AuditAction, audit_log
from app.core.exceptions import BusinessValidationError, ConflictError, NotFoundError
from app.models.academic import AcademicYear, Class
from app.models.enrollment import AssignmentStatus
from app.models.fee import (
    EnrollmentFee,
    EnrollmentFeeStatus,
    FeeAssignmentScope,
    FeeCategory,
    FeeVariant,
    PaymentAllocation,
    is_not_cash_due,
)
from app.repositories import enrollment_repository as repo
from app.schemas.enrollment import FeeVariantResponse, InKindDeposit
from app.services import fee_entitlements as entitlements
from app.services import fees_paid
from app.services.deletion import Dependent

#: Ce que la base range dans les colonnes générées quand la dimension est vide.
#: Comparer ces sentinelles plutôt que des `NULL` est ce qui a rendu la
#: contrainte d'unicité `uq_fee_variant_dimensions` réellement effective.
_NO_SCOPE = ""
_NO_SERIES = 0


# ---------------------------------------------------------------------------
# Quels tarifs une inscription peut recevoir
# ---------------------------------------------------------------------------


def applicable_scope_keys(assignment_status: object) -> tuple[str, ...]:
    """Portées qu'une inscription peut se voir appliquer, sentinelle comprise.

    Un tarif sans portée s'applique à tout le monde : c'est ce qui permet aux
    grilles déjà configurées de continuer à fonctionner sans qu'on y touche.

    Une inscription dont le statut d'affectation n'est pas renseigné ne reçoit
    QUE ces tarifs-là. Lui donner le tarif affecté ou le tarif non affecté
    reviendrait à choisir pour l'école entre deux montants différents, et la
    famille le découvrirait sur sa facture.
    """
    if assignment_status is None:
        return (_NO_SCOPE,)

    subsidised = AssignmentStatus(assignment_status).is_subsidised
    scope = FeeAssignmentScope.AFFECTE if subsidised else FeeAssignmentScope.NON_AFFECTE
    return (_NO_SCOPE, scope.value)


def applicable_series_keys(series_id: int | None) -> tuple[int, ...]:
    """Séries qu'une classe peut se voir appliquer, sentinelle comprise.

    Un tarif sans série vaut pour tout le niveau ; une classe sans série ne
    peut recevoir que ceux-là.
    """
    if series_id is None:
        return (_NO_SERIES,)
    return (_NO_SERIES, series_id)


def _specificity(variant: FeeVariant) -> tuple[bool, bool]:
    """Plus le tarif est précis, plus il l'emporte.

    Une portée renseignée bat une portée vide ; à portée égale, une série
    renseignée bat une série vide. C'est l'ordre que l'école a en tête quand
    elle ajoute un tarif affecté par-dessus sa grille générale : le nouveau
    remplace l'ancien pour les élèves concernés, il ne s'y ajoute pas.
    """
    return (variant.assignment_scope is not None, variant.series_id is not None)


def most_specific_variant_per_category(variants: Iterable[FeeVariant]) -> list[FeeVariant]:
    """Ne garde qu'un tarif par catégorie de frais : le plus spécifique.

    Sans ce tri, une école qui possède déjà sa grille et ajoute le tarif
    affecté de la Scolarité T1 — le geste même que la fonctionnalité existe
    pour permettre — voit chaque élève affecté inscrit ensuite recevoir DEUX
    lignes T1 : la dette est doublée, l'échéancier est doublé, et le certificat
    de scolarité de la famille est retenu pour un impayé qui n'existe pas.

    Les égalités ne peuvent plus se produire : à spécificité égale, deux tarifs
    de la même catégorie partagent leurs cinq dimensions et se heurtent à
    `uq_fee_variant_dimensions`. On garde tout de même le premier rencontré
    pour que le résultat reste déterministe si une base ancienne en portait.
    """
    retenus: dict[int, FeeVariant] = {}
    for variant in variants:
        courant = retenus.get(variant.fee_category_id)
        if courant is None or _specificity(variant) > _specificity(courant):
            retenus[variant.fee_category_id] = variant
    return list(retenus.values())


async def _load_class(db: AsyncSession, class_id: int) -> Class:
    class_ = (await db.execute(select(Class).where(Class.id == class_id))).scalar_one_or_none()
    if class_ is None:
        raise BusinessValidationError(f"Class {class_id} not found")
    return class_


async def get_mandatory_fee_variants(
    db: AsyncSession,
    class_id: int,
    academic_year_id: int,
    assignment_status: object = None,
) -> list[FeeVariant]:
    """Un tarif obligatoire par catégorie pour cette classe et cette année.

    Refactor #97 : `Class` est universelle (pas de `academic_year_id`), l'année
    est donc passée explicitement par l'appelant.
    """
    class_ = await _load_class(db, class_id)

    stmt = (
        select(FeeVariant)
        .join(FeeCategory, FeeVariant.fee_category_id == FeeCategory.id)
        .where(
            FeeVariant.academic_year_id == academic_year_id,
            FeeVariant.level_id == class_.level_id,
            FeeVariant.series_key.in_(applicable_series_keys(class_.series_id)),
            FeeVariant.scope_key.in_(applicable_scope_keys(assignment_status)),
            FeeCategory.is_mandatory.is_(True),
        )
        .order_by(FeeVariant.fee_category_id, FeeVariant.id)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return most_specific_variant_per_category(rows)


# ---------------------------------------------------------------------------
# De la grille tarifaire à la dette de l'élève
# ---------------------------------------------------------------------------


async def _count_enrollment_fees(db: AsyncSession, enrollment_id: int) -> int:
    """Nombre de lignes de frais portees par une inscription."""
    stmt = select(EnrollmentFee.id).where(EnrollmentFee.enrollment_id == enrollment_id)
    return len((await db.execute(stmt)).scalars().all())


async def _categories_already_billed(db: AsyncSession, enrollment_id: int) -> set[int]:
    """Catégories déjà facturées à cette inscription.

    Le garde porte sur la catégorie, pas sur l'identifiant du tarif : deux
    tarifs différents de la Scolarité T1 restent une seule dette de Scolarité
    T1. Dédoublonner sur le tarif laissait justement passer la seconde ligne
    quand la régénération retenait, cette fois, le tarif affecté.
    """
    stmt = (
        select(FeeVariant.fee_category_id)
        .join(EnrollmentFee, EnrollmentFee.fee_variant_id == FeeVariant.id)
        .where(EnrollmentFee.enrollment_id == enrollment_id)
    )
    return set((await db.execute(stmt)).scalars().all())


async def create_mandatory_enrollment_fees(
    db: AsyncSession,
    enrollment_id: int,
    class_id: int,
    academic_year_id: int,
    assignment_status: object = None,
) -> None:
    """Crée les `EnrollmentFee` des frais obligatoires d'une classe.

    Idempotent : une catégorie déjà facturée n'est pas refacturée.
    """
    variants = await get_mandatory_fee_variants(db, class_id, academic_year_id, assignment_status)
    if not variants:
        return

    deja_facturees = await _categories_already_billed(db, enrollment_id)

    for variant in variants:
        if variant.fee_category_id in deja_facturees:
            continue
        db.add(
            EnrollmentFee(
                enrollment_id=enrollment_id,
                fee_variant_id=variant.id,
                # Recopiee du tarif : c'est elle que porte la contrainte
                # `uq_enrollment_fee_category`, une categorie par inscription.
                fee_category_id=variant.fee_category_id,
                amount=variant.amount,
            )
        )

    await db.flush()


async def regenerate_enrollment_fees(
    db: AsyncSession,
    enrollment_id: int,
    regenerated_by: int,
) -> dict:
    """Régénère les frais obligatoires d'une inscription.

    1. Conserve les frais qui portent une allocation de versement
    2. Supprime les autres (remplaçables sans conséquence comptable)
    3. Re-crée les frais obligatoires manquants (idempotent)

    Le tri se fait sur les allocations, seule source vivante depuis la
    migration 0028. Le garde lisait auparavant `EnrollmentFee.payments`,
    c'est-à-dire la colonne `payments.enrollment_fee_id`, plus jamais
    renseignée : il croyait donc qu'aucun frais n'était payé, tentait de
    tous les détruire, et la clé étrangère `RESTRICT` faisait échouer
    l'opération entière sous les yeux de l'utilisateur.
    """
    enrollment = await repo.get_enrollment_by_id(db, enrollment_id)
    if enrollment is None:
        raise NotFoundError("Enrollment", enrollment_id)

    protected_fee_ids = await fees_paid.fee_ids_with_allocations(db, enrollment_id)

    deleted_count = 0
    kept_count = 0

    for ef in list(enrollment.enrollment_fees):
        # On ne détruit jamais un frais sur lequel de l'argent est imputé :
        # le versement perdrait sa contrepartie, et le journal d'audit ne
        # rattrape pas un trou comptable.
        if ef.id in protected_fee_ids or is_not_cash_due(ef.status):
            # Versement imputé, exonération, ou dépôt en nature : on ne
            # détruit pas. Un in_kind n'a pas d'allocation — sans ce garde
            # la régénération le recréerait en pending.
            kept_count += 1
        else:
            await db.delete(ef)
            deleted_count += 1

    await db.flush()

    avant_creation = await _count_enrollment_fees(db, enrollment_id)
    await create_mandatory_enrollment_fees(
        db,
        enrollment_id,
        enrollment.class_id,
        enrollment.academic_year_id,
        enrollment.assignment_status,
    )
    created_count = await _count_enrollment_fees(db, enrollment_id) - avant_creation

    await audit_log(
        db,
        entity_type="enrollment",
        action=AuditAction.UPDATE,
        user_id=regenerated_by,
        entity_id=enrollment_id,
        new_values={
            "action": "regenerate_fees",
            "deleted": deleted_count,
            "created": created_count,
            "kept_with_payments": kept_count,
        },
    )

    # La régénération réussit toujours, mais elle n'a pas fait tout ce que
    # l'utilisateur pouvait croire : les frais déjà payés sont restés en
    # place. Le dire, chiffré, plutôt que de le laisser deviner.
    supprimes = Dependent("frais remplacé", "frais remplacés", deleted_count)
    conserves = Dependent(
        "frais conservé car un versement y est imputé",
        "frais conservés car des versements y sont imputés",
        kept_count,
    )
    crees = Dependent("frais créé", "frais créés", created_count)
    parties = [d.phrase() for d in (crees, supprimes, conserves) if d.count]
    message = (
        f"Frais régénérés : {', '.join(parties)}."
        if parties
        else "Aucun frais à régénérer pour cette inscription."
    )

    return {
        "deleted": deleted_count,
        "created": created_count,
        "kept": kept_count,
        "message": message,
    }


# ---------------------------------------------------------------------------
# Aperçu des frais applicables à une classe
# ---------------------------------------------------------------------------


def _to_variant_response(fv: FeeVariant) -> FeeVariantResponse:
    return FeeVariantResponse(
        id=fv.id,
        fee_category_id=fv.fee_category_id,
        category_name=fv.category.name if fv.category else str(fv.fee_category_id),
        entitlements=entitlements.read(fv.category),
        is_mandatory=fv.category.is_mandatory if fv.category else True,
        accepts_in_kind=bool(fv.category.accepts_in_kind) if fv.category else False,
        level_id=fv.level_id,
        series_id=fv.series_id,
        academic_year_id=fv.academic_year_id,
        amount=fv.amount,
        description=fv.description,
    )


def _is_mandatory(fv: FeeVariant) -> bool:
    return fv.category is None or bool(fv.category.is_mandatory)


async def get_applicable_fee_variants(
    db: AsyncSession,
    class_id: int,
    academic_year_id: int | None = None,
    assignment_status: object = None,
) -> list[FeeVariantResponse]:
    """Aperçu des tarifs applicables à une classe.

    Frais obligatoires : un seul par catégorie, le plus spécifique. L'aperçu et
    la génération réelle doivent annoncer la même facture, sans quoi la caisse
    et le secrétariat lisent deux montants différents.

    Frais optionnels : le niveau peut être vide (cantine, transport : un prix
    fixe qui ne dépend pas du niveau), et plusieurs options coexistent
    légitimement — on ne les réduit donc pas à une par catégorie.
    """
    class_ = await _load_class(db, class_id)

    if academic_year_id is None:
        current_ay = (
            await db.execute(select(AcademicYear).where(AcademicYear.is_current.is_(True)))
        ).scalar_one_or_none()
        if current_ay is None:
            raise BusinessValidationError("Aucune année académique courante configurée.")
        academic_year_id = current_ay.id

    stmt = (
        select(FeeVariant)
        .join(FeeCategory, FeeVariant.fee_category_id == FeeCategory.id)
        .options(selectinload(FeeVariant.category))
        .where(
            FeeVariant.academic_year_id == academic_year_id,
            FeeVariant.series_key.in_(applicable_series_keys(class_.series_id)),
            FeeVariant.scope_key.in_(applicable_scope_keys(assignment_status)),
            or_(
                # Obligatoire : le niveau doit correspondre exactement.
                and_(FeeCategory.is_mandatory, FeeVariant.level_id == class_.level_id),
                # Optionnel : niveau correspondant, ou global (niveau vide).
                and_(
                    FeeCategory.is_mandatory.is_(False),
                    or_(
                        FeeVariant.level_id == class_.level_id,
                        FeeVariant.level_id.is_(None),
                    ),
                ),
            ),
        )
        .order_by(FeeCategory.is_mandatory.desc(), FeeVariant.fee_category_id, FeeVariant.id)
    )
    rows: Sequence[FeeVariant] = (await db.execute(stmt)).scalars().all()

    retenus = {
        fv.id for fv in most_specific_variant_per_category(fv for fv in rows if _is_mandatory(fv))
    }
    retenus.update(fv.id for fv in rows if not _is_mandatory(fv))

    return [_to_variant_response(fv) for fv in rows if fv.id in retenus]


def _stamp_in_kind(fee: EnrollmentFee, deposited_by: int, *, when: datetime) -> None:
    fee.status = EnrollmentFeeStatus.IN_KIND
    fee.deposited_at = when
    fee.deposited_by_user_id = deposited_by


# ---------------------------------------------------------------------------
# Dépôt en nature — le parent apporte l'article, la ligne n'est plus due
# ---------------------------------------------------------------------------


async def apply_in_kind_deposits(
    db: AsyncSession,
    enrollment_id: int,
    deposits: Sequence[InKindDeposit],
    *,
    deposited_by: int,
) -> None:
    """Coche les dépôts saisis à l'inscription. Les autres lignes restent dues."""
    wanted = {int(d.fee_category_id) for d in deposits if d.deposited}
    if not wanted:
        return

    stmt = (
        select(EnrollmentFee)
        .join(FeeCategory, FeeCategory.id == EnrollmentFee.fee_category_id)
        .where(
            EnrollmentFee.enrollment_id == enrollment_id,
            EnrollmentFee.fee_category_id.in_(wanted),
            FeeCategory.accepts_in_kind.is_(True),
            EnrollmentFee.status == EnrollmentFeeStatus.PENDING,
        )
    )
    now = datetime.now()
    for fee in (await db.execute(stmt)).scalars().all():
        _stamp_in_kind(fee, deposited_by, when=now)
    await db.flush()


async def mark_in_kind_deposit(
    db: AsyncSession,
    *,
    enrollment_id: int,
    fee_id: int,
    deposited_by: int,
) -> EnrollmentFee:
    """Dépôt tardif : pending sans allocation → in_kind. Sinon 409."""
    fee = (
        await db.execute(
            select(EnrollmentFee).where(
                EnrollmentFee.id == fee_id,
                EnrollmentFee.enrollment_id == enrollment_id,
            )
        )
    ).scalar_one_or_none()
    if fee is None:
        raise NotFoundError("EnrollmentFee", fee_id)

    if fee.status == EnrollmentFeeStatus.IN_KIND:
        raise ConflictError("Cette ligne est déjà marquée déposée.")

    if fee.status != EnrollmentFeeStatus.PENDING:
        raise ConflictError(
            "Impossible de marquer ce frais comme déposé : un versement y est "
            "déjà imputé, ou la ligne n'est plus due. On n'annule pas un paiement."
        )

    has_alloc = (
        await db.execute(
            select(PaymentAllocation.id)
            .where(PaymentAllocation.enrollment_fee_id == fee.id)
            .limit(1)
        )
    ).first()
    if has_alloc is not None:
        raise ConflictError(
            "Impossible de marquer ce frais comme déposé : un versement y est déjà imputé."
        )

    category = (
        await db.execute(select(FeeCategory).where(FeeCategory.id == fee.fee_category_id))
    ).scalar_one_or_none()
    if category is None or not category.accepts_in_kind:
        raise ConflictError("Ce frais n'accepte pas de dépôt en nature.")

    _stamp_in_kind(fee, deposited_by, when=datetime.now())
    await db.flush()

    await audit_log(
        db,
        entity_type="enrollment_fee",
        action=AuditAction.UPDATE,
        user_id=deposited_by,
        entity_id=fee.id,
        new_values={
            "action": "in_kind_deposit",
            "enrollment_id": enrollment_id,
            "fee_category_id": fee.fee_category_id,
            "status": EnrollmentFeeStatus.IN_KIND.value,
        },
    )
    return fee
