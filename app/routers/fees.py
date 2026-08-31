"""Router fees — CRUD endpoints pour FeeCategory et FeeVariant."""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import TokenData, get_current_user, get_tenant_db, require_permission
from app.schemas.fee import (
    FeeCategoryCreate,
    FeeCategoryListResponse,
    FeeCategoryResponse,
    FeeCategoryUpdate,
    FeePropagationPreview,
    FeePropagationRequest,
    FeePropagationResult,
    FeeVariantCreate,
    FeeVariantListResponse,
    FeeVariantResponse,
    FeeVariantUpdate,
    MandatoryBasketLine,
    MandatoryBasketResponse,
    OptionalFeeOptionCreate,
    OptionalFeeOptionListResponse,
    OptionalFeeOptionResponse,
    OptionalFeeOptionUpdate,
)
from app.services import enrollment_fees, fee_propagation, fee_service

router = APIRouter(prefix="/admin", tags=["fees"])


# ---------------------------------------------------------------------------
# Fee Categories
# ---------------------------------------------------------------------------


@router.get("/fee-categories", response_model=FeeCategoryListResponse)
async def list_fee_categories(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    _: None = require_permission("admin:fee-categories:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> FeeCategoryListResponse:
    """Liste paginee des categories de frais."""
    return await fee_service.list_fee_categories(db, page=page, size=size)


@router.post(
    "/fee-categories",
    response_model=FeeCategoryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_fee_category(
    data: FeeCategoryCreate,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("admin:fee-categories:create"),
    db: AsyncSession = Depends(get_tenant_db),
) -> FeeCategoryResponse:
    """Cree une nouvelle categorie de frais."""
    return await fee_service.create_fee_category(db, data, created_by=current_user.user_id)


@router.get("/fee-categories/{category_id}", response_model=FeeCategoryResponse)
async def get_fee_category(
    category_id: int,
    _: None = require_permission("admin:fee-categories:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> FeeCategoryResponse:
    """Retourne une categorie de frais par ID."""
    return await fee_service.get_fee_category(db, category_id)


@router.patch("/fee-categories/{category_id}", response_model=FeeCategoryResponse)
async def update_fee_category(
    category_id: int,
    data: FeeCategoryUpdate,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("admin:fee-categories:update"),
    db: AsyncSession = Depends(get_tenant_db),
) -> FeeCategoryResponse:
    """Met a jour une categorie de frais (patch partiel)."""
    return await fee_service.update_fee_category(
        db, category_id, data, updated_by=current_user.user_id
    )


@router.delete("/fee-categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_fee_category(
    category_id: int,
    cascade: bool = Query(
        False,
        description=(
            "Confirme la suppression des elements qui en dependent. Sans lui, un "
            "409 renvoie l'inventaire de ce qui serait emporte."
        ),
    ),
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("admin:fee-categories:delete"),
    db: AsyncSession = Depends(get_tenant_db),
) -> None:
    """Supprime une categorie de frais."""
    await fee_service.delete_fee_category(
        db, category_id, deleted_by=current_user.user_id, cascade=cascade
    )


# ---------------------------------------------------------------------------
# Fee Variants
# ---------------------------------------------------------------------------


@router.get("/fee-variants", response_model=FeeVariantListResponse)
async def list_fee_variants(
    category_id: int | None = Query(None),
    level_id: int | None = Query(None),
    academic_year_id: int | None = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    _: None = require_permission("admin:fee-variants:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> FeeVariantListResponse:
    """Liste paginee des variantes de frais avec filtres."""
    return await fee_service.list_fee_variants(
        db,
        page=page,
        size=size,
        category_id=category_id,
        level_id=level_id,
        academic_year_id=academic_year_id,
    )


@router.post(
    "/fee-variants",
    response_model=FeeVariantResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_fee_variant(
    data: FeeVariantCreate,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("admin:fee-variants:create"),
    db: AsyncSession = Depends(get_tenant_db),
) -> FeeVariantResponse:
    """Cree une nouvelle variante de frais."""
    return await fee_service.create_fee_variant(db, data, created_by=current_user.user_id)


@router.get("/fee-variants/{variant_id}", response_model=FeeVariantResponse)
async def get_fee_variant(
    variant_id: int,
    _: None = require_permission("admin:fee-variants:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> FeeVariantResponse:
    """Retourne une variante de frais par ID."""
    return await fee_service.get_fee_variant(db, variant_id)


@router.patch("/fee-variants/{variant_id}", response_model=FeeVariantResponse)
async def update_fee_variant(
    variant_id: int,
    data: FeeVariantUpdate,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("admin:fee-variants:update"),
    db: AsyncSession = Depends(get_tenant_db),
) -> FeeVariantResponse:
    """Met a jour une variante de frais (patch partiel)."""
    return await fee_service.update_fee_variant(
        db, variant_id, data, updated_by=current_user.user_id
    )


@router.get(
    "/fee-variants/mandatory-basket",
    response_model=MandatoryBasketResponse,
    summary="Socle obligatoire par niveau et par public, pour la simulation de grille",
)
async def mandatory_basket(
    academic_year_id: int = Query(..., description="Annee dont on chiffre la grille"),
    _: None = require_permission("fees:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> MandatoryBasketResponse:
    """Ce que chaque niveau doit, pour chaque public, en frais obligatoires.

    L'ecran de simulation calculait ce total lui-meme, en reimplementant
    l'arbitrage du tarif le plus specifique. La regle vivait donc dans deux
    langages, et elle a diverge : la simulation oubliait d'ecarter les tarifs
    d'une serie etrangere et annoncait des francs que l'eleve ne paierait pas.

    La regle reste dans `enrollment_fees`, seule. On rend toutes les
    combinaisons d'un coup, six par niveau, plutot qu'un appel par bascule de
    selecteur : l'ecran redevient une lecture, et il n'attend pas le reseau
    pendant que la personne reflechit.
    """
    paniers = await enrollment_fees.mandatory_totals_by_audience(db, academic_year_id)
    return MandatoryBasketResponse(items=[MandatoryBasketLine.model_validate(p) for p in paniers])


@router.get(
    "/fee-variants/{variant_id}/propagation-preview",
    response_model=FeePropagationPreview,
)
async def preview_fee_variant_propagation(
    variant_id: int,
    _: None = require_permission("admin:fee-variants:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> FeePropagationPreview:
    """Ce que la repercussion de ce tarif ferait, chiffre, sans rien ecrire.

    L'ecole doit voir l'impact avant de confirmer : combien d'inscriptions
    portent ce tarif, combien de lignes seraient reecrites, combien seraient
    conservees parce qu'un versement y est impute, et de combien la dette
    totale bougerait.

    `fees_to_create` compte les inscriptions auxquelles ce tarif doit une
    ligne et qui n'en portent aucune de sa categorie. Il est rendu dans tous
    les cas : la confirmation ne les cree que si on le lui demande, mais
    l'ecole doit d'abord savoir qu'elles existent.
    """
    return await fee_propagation.preview_variant_propagation(db, variant_id)


@router.post("/fee-variants/{variant_id}/propagate", response_model=FeePropagationResult)
async def propagate_fee_variant(
    variant_id: int,
    data: FeePropagationRequest | None = None,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("admin:fee-variants:update"),
    db: AsyncSession = Depends(get_tenant_db),
) -> FeePropagationResult:
    """Repercute le montant de ce tarif sur les inscriptions qui le portent.

    Borne a la categorie et au tarif modifies, pour l'annee de ce tarif. Les
    lignes qui portent deja un versement ne sont pas touchees : le recu remis
    a la famille resterait vrai, et le reste du ne peut pas devenir negatif.

    Le corps est facultatif, et son absence vaut `create_missing: false` :
    repercuter ne fait alors que reecrire des montants, sans creer une seule
    ligne. Corriger une faute de frappe sur le prix de la tenue ne doit
    endetter personne de plus. La creation des lignes manquantes se demande,
    apres avoir lu l'apercu qui les compte.

    Meme droit que la modification du tarif : repercuter est la suite du meme
    geste, et un slug supplementaire laisserait sans bouton les ecoles
    provisionnees avant sa migration.
    """
    async with db.begin_nested():
        result = await fee_propagation.apply_variant_propagation(
            db,
            variant_id,
            applied_by=current_user.user_id,
            create_missing=data.create_missing if data else False,
        )
    await db.commit()
    return result


@router.delete("/fee-variants/{variant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_fee_variant(
    variant_id: int,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("admin:fee-variants:delete"),
    db: AsyncSession = Depends(get_tenant_db),
) -> None:
    """Supprime une variante de frais."""
    await fee_service.delete_fee_variant(db, variant_id, deleted_by=current_user.user_id)


# ---------------------------------------------------------------------------
# Optional Fee Options
# ---------------------------------------------------------------------------


@router.get("/fee-options", response_model=OptionalFeeOptionListResponse)
async def list_fee_options(
    category_id: int | None = Query(None),
    academic_year_id: int | None = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(100, ge=1, le=200),
    _: None = require_permission("admin:fee-options:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> OptionalFeeOptionListResponse:
    """Liste paginee des options de frais optionnels avec filtres."""
    return await fee_service.list_optional_fee_options(
        db,
        page=page,
        size=size,
        category_id=category_id,
        academic_year_id=academic_year_id,
    )


@router.post(
    "/fee-options",
    response_model=OptionalFeeOptionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_fee_option(
    data: OptionalFeeOptionCreate,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("admin:fee-options:create"),
    db: AsyncSession = Depends(get_tenant_db),
) -> OptionalFeeOptionResponse:
    """Cree une nouvelle option de frais optionnel."""
    return await fee_service.create_optional_fee_option(db, data, created_by=current_user.user_id)


@router.get("/fee-options/{option_id}", response_model=OptionalFeeOptionResponse)
async def get_fee_option(
    option_id: int,
    _: None = require_permission("admin:fee-options:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> OptionalFeeOptionResponse:
    """Retourne une option de frais optionnel par ID."""
    return await fee_service.get_optional_fee_option(db, option_id)


@router.patch("/fee-options/{option_id}", response_model=OptionalFeeOptionResponse)
async def update_fee_option(
    option_id: int,
    data: OptionalFeeOptionUpdate,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("admin:fee-options:update"),
    db: AsyncSession = Depends(get_tenant_db),
) -> OptionalFeeOptionResponse:
    """Met a jour une option de frais optionnel (patch partiel)."""
    return await fee_service.update_optional_fee_option(
        db, option_id, data, updated_by=current_user.user_id
    )


@router.delete("/fee-options/{option_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_fee_option(
    option_id: int,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("admin:fee-options:delete"),
    db: AsyncSession = Depends(get_tenant_db),
) -> None:
    """Supprime une option de frais optionnel."""
    await fee_service.delete_optional_fee_option(db, option_id, deleted_by=current_user.user_id)
