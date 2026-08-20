"""Router fees — CRUD endpoints pour FeeCategory et FeeVariant."""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import TokenData, get_current_user, get_tenant_db, require_permission
from app.schemas.fee import (
    FeeCategoryCreate,
    FeeCategoryListResponse,
    FeeCategoryResponse,
    FeeCategoryUpdate,
    FeeVariantCreate,
    FeeVariantListResponse,
    FeeVariantResponse,
    FeeVariantUpdate,
    OptionalFeeOptionCreate,
    OptionalFeeOptionListResponse,
    OptionalFeeOptionResponse,
    OptionalFeeOptionUpdate,
)
from app.services import fee_service

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
