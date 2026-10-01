"""Router inscriptions — dépôts en nature et aperçu des tarifs applicables.

Sorti de `enrollments.py`, qui dépassait la taille qu'on relit d'une traite.
Inclus AVANT lui dans `main.py` : `/in-kind-roster` et `/fee-variants` sont
des chemins littéraux qui doivent passer avant `/{enrollment_id}`.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import TokenData, get_current_user, get_tenant_db, require_permission
from app.schemas.enrollment import (
    DepositableFeeListResponse,
    DepositableFeeResponse,
    FeeVariantResponse,
    InKindDepositResponse,
    InKindRosterResponse,
    InKindRosterRowResponse,
)
from app.services import enrollment_fees

router = APIRouter(prefix="/enrollments", tags=["enrollments"])


@router.get(
    "/in-kind-roster",
    response_model=InKindRosterResponse,
    summary="La classe entiere, pour la saisie en lot du profil et des depots",
)
async def in_kind_roster(
    class_id: int = Query(..., description="Classe sur laquelle l'educateur travaille"),
    academic_year_id: int = Query(..., description="Annee de la classe"),
    _: None = require_permission("enrollments:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> InKindRosterResponse:
    """Ce qu'il reste a renseigner sur chaque eleve d'une classe.

    Une classe a la fois, jamais toute l'ecole : c'est l'unite de travail de
    l'educateur, sa liste a la main. En un appel, parce que soixante-dix-huit
    fiches ouvertes une par une, c'est un travail qui ne se termine pas.

    Chaque ligne porte le profil tel qu'il est, `null` compris, et seulement
    les articles que cette inscription-la peut recevoir. Une case affichee sur
    un frais que l'eleve ne doit pas serait une invitation a se tromper.
    """
    lignes = await enrollment_fees.in_kind_roster(
        db, class_id=class_id, academic_year_id=academic_year_id
    )
    return InKindRosterResponse(
        items=[InKindRosterRowResponse.model_validate(ligne) for ligne in lignes]
    )


@router.get("/fee-variants", response_model=list[FeeVariantResponse])
async def get_applicable_fee_variants(
    class_id: int = Query(..., description="ID de la classe pour la resolution des frais"),
    academic_year_id: int | None = Query(
        None,
        description=(
            "AY pour le matching des frais. Si omis, l'AY courante est utilisée. "
            "Class étant universel (refactor #97), l'AY n'est plus inférée depuis la classe."
        ),
    ),
    assignment_status: str | None = Query(
        None,
        description="Statut d'affectation de l'inscription, pour resoudre les tarifs qui en dependent.",
    ),
    is_new_student: bool | None = Query(
        None,
        description=(
            "Profil de l'inscription. Omis, l'apercu ne montre que les tarifs "
            "sans profil, comme une inscription non tranchee."
        ),
    ),
    _: None = require_permission("enrollments:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> list[FeeVariantResponse]:
    """Retourne les fee variants applicables pour une classe donnee.

    Les deux dimensions sont passees au service, et c'est le point de cet
    endpoint : sans elles il resout les tarifs comme une inscription dont on
    ne sait rien, donc en ecartant tout tarif porteur d'une portee ou d'un
    profil. Le guichet lisait alors une facture ou la chemise cartonnee
    n'apparaissait jamais, alors que l'inscription creee juste apres la
    portait. L'apercu et la generation reelle doivent annoncer la meme chose.
    """
    return await enrollment_fees.get_applicable_fee_variants(
        db,
        class_id,
        academic_year_id,
        assignment_status=assignment_status,
        is_new_student=is_new_student,
    )


@router.get(
    "/{enrollment_id}/in-kind-fees",
    response_model=DepositableFeeListResponse,
    summary="Les articles deposables de cette inscription, sans montant",
)
async def get_depositable_fees(
    enrollment_id: int,
    _: None = require_permission("enrollments:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> DepositableFeeListResponse:
    """Ce que cette inscription peut recevoir en depot, et ou ca en est.

    `enrollments:read` et non `payments:read` : la reponse ne porte aucun
    montant, seulement le nom de l'article et son etat. C'est la lecture qui
    manquait a l'educateur — il a le droit de poser un depot depuis la fiche,
    mais la seule liste qui montrait ses articles etait faite de sommes, donc
    fermee, et l'ecran lui repondait une porte close la ou il peut agir.

    Le detail des frais reste, lui, derriere `payments:read`. Ouvrir cette
    liste-ci n'ouvre rien d'autre : un article sans son tarif ne dit pas ce que
    la famille doit.
    """
    articles = await enrollment_fees.depositable_fees(db, enrollment_id=enrollment_id)
    return DepositableFeeListResponse(
        items=[DepositableFeeResponse.model_validate(article) for article in articles]
    )


@router.patch(
    "/{enrollment_id}/fees/{fee_id}/in-kind-deposit",
    response_model=InKindDepositResponse,
)
async def mark_in_kind_deposit(
    enrollment_id: int,
    fee_id: int,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("enrollments:update"),
    db: AsyncSession = Depends(get_tenant_db),
) -> InKindDepositResponse:
    """Dépôt tardif : pending sans versement → déposé. Sinon 409."""
    async with db.begin_nested():
        fee = await enrollment_fees.mark_in_kind_deposit(
            db,
            enrollment_id=enrollment_id,
            fee_id=fee_id,
            deposited_by=current_user.user_id,
        )
    await db.commit()
    return InKindDepositResponse(
        id=fee.id,
        status=fee.status,
        deposited_at=fee.deposited_at,
        deposited_by_user_id=fee.deposited_by_user_id,
    )


@router.delete(
    "/{enrollment_id}/fees/{fee_id}/in-kind-deposit",
    response_model=InKindDepositResponse,
    summary="Annuler un depot en nature pose par erreur",
)
async def cancel_in_kind_deposit(
    enrollment_id: int,
    fee_id: int,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("enrollments:update"),
    db: AsyncSession = Depends(get_tenant_db),
) -> InKindDepositResponse:
    """La ligne redevient due. 409 si elle n'etait pas deposee.

    Marquer un article depose retire la ligne du du, et l'application n'offrait
    aucun retour : un depot pose par erreur a deja du etre corrige a la main
    dans la base. Avec une saisie en lot, ou l'educateur coche quarante cases
    d'affilee, ce manque n'etait plus tenable.

    Rend le meme corps que la pose : l'ecran lit un seul contrat, quel que
    soit le sens du geste.
    """
    async with db.begin_nested():
        fee = await enrollment_fees.cancel_in_kind_deposit(
            db,
            enrollment_id=enrollment_id,
            fee_id=fee_id,
            cancelled_by=current_user.user_id,
        )
    await db.commit()
    return InKindDepositResponse(
        id=fee.id,
        status=fee.status,
        deposited_at=fee.deposited_at,
        deposited_by_user_id=fee.deposited_by_user_id,
    )
