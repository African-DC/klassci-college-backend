"""Service fee — logique metier CRUD pour FeeCategory et FeeVariant."""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditAction, audit_log
from app.core.exceptions import NotFoundError
from app.repositories import fee_repository as repo
from app.schemas.fee import (
    FeeCategoryCreate,
    FeeCategoryListResponse,
    FeeCategoryResponse,
    FeeCategoryUpdate,
    FeeVariantCreate,
    FeeVariantListResponse,
    FeeVariantResponse,
    FeeVariantUpdate,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# FeeCategory
# ---------------------------------------------------------------------------


def _fee_category_to_response(c: object) -> FeeCategoryResponse:
    return FeeCategoryResponse.model_validate(c)


async def list_fee_categories(
    db: AsyncSession,
    *,
    page: int = 1,
    size: int = 20,
) -> FeeCategoryListResponse:
    categories, total = await repo.list_fee_categories(db, page=page, size=size)
    return FeeCategoryListResponse(
        items=[_fee_category_to_response(c) for c in categories],
        total=total,
        page=page,
        size=size,
    )


async def get_fee_category(db: AsyncSession, category_id: int) -> FeeCategoryResponse:
    category = await repo.get_fee_category_by_id(db, category_id)
    if category is None:
        raise NotFoundError("FeeCategory", category_id)
    return _fee_category_to_response(category)


async def create_fee_category(
    db: AsyncSession, data: FeeCategoryCreate, *, created_by: int
) -> FeeCategoryResponse:
    async with db.begin_nested():
        category = await repo.create_fee_category(db, **data.model_dump())
        await audit_log(
            db,
            entity_type="fee_category",
            action=AuditAction.CREATE,
            user_id=created_by,
            entity_id=category.id,
            new_values=data.model_dump(mode="json"),
        )
    await db.commit()
    refreshed = await repo.get_fee_category_by_id(db, category.id)
    if refreshed is None:
        raise NotFoundError("FeeCategory", category.id)
    return _fee_category_to_response(refreshed)


async def update_fee_category(
    db: AsyncSession, category_id: int, data: FeeCategoryUpdate, *, updated_by: int
) -> FeeCategoryResponse:
    category = await repo.get_fee_category_by_id(db, category_id)
    if category is None:
        raise NotFoundError("FeeCategory", category_id)
    changes = data.model_dump(exclude_none=True, mode="json")
    if not changes:
        return _fee_category_to_response(category)
    async with db.begin_nested():
        await repo.update_fee_category(db, category, **changes)
        await audit_log(
            db,
            entity_type="fee_category",
            action=AuditAction.UPDATE,
            user_id=updated_by,
            entity_id=category_id,
            new_values=changes,
        )
    await db.commit()
    refreshed = await repo.get_fee_category_by_id(db, category_id)
    if refreshed is None:
        raise NotFoundError("FeeCategory", category_id)
    return _fee_category_to_response(refreshed)


async def delete_fee_category(
    db: AsyncSession, category_id: int, *, deleted_by: int
) -> None:
    category = await repo.get_fee_category_by_id(db, category_id)
    if category is None:
        raise NotFoundError("FeeCategory", category_id)
    async with db.begin_nested():
        await repo.delete_fee_category(db, category)
        await audit_log(
            db,
            entity_type="fee_category",
            action=AuditAction.DELETE,
            user_id=deleted_by,
            entity_id=category_id,
        )
    await db.commit()


# ---------------------------------------------------------------------------
# FeeVariant
# ---------------------------------------------------------------------------


def _fee_variant_to_response(v: object) -> FeeVariantResponse:
    return FeeVariantResponse.model_validate(v)


async def list_fee_variants(
    db: AsyncSession,
    *,
    page: int = 1,
    size: int = 20,
    category_id: int | None = None,
    level_id: int | None = None,
    academic_year_id: int | None = None,
) -> FeeVariantListResponse:
    variants, total = await repo.list_fee_variants(
        db,
        page=page,
        size=size,
        category_id=category_id,
        level_id=level_id,
        academic_year_id=academic_year_id,
    )
    return FeeVariantListResponse(
        items=[_fee_variant_to_response(v) for v in variants],
        total=total,
        page=page,
        size=size,
    )


async def get_fee_variant(db: AsyncSession, variant_id: int) -> FeeVariantResponse:
    variant = await repo.get_fee_variant_by_id(db, variant_id)
    if variant is None:
        raise NotFoundError("FeeVariant", variant_id)
    return _fee_variant_to_response(variant)


async def create_fee_variant(
    db: AsyncSession, data: FeeVariantCreate, *, created_by: int
) -> FeeVariantResponse:
    async with db.begin_nested():
        variant = await repo.create_fee_variant(db, **data.model_dump())
        await audit_log(
            db,
            entity_type="fee_variant",
            action=AuditAction.CREATE,
            user_id=created_by,
            entity_id=variant.id,
            new_values=data.model_dump(mode="json"),
        )
    await db.commit()
    refreshed = await repo.get_fee_variant_by_id(db, variant.id)
    if refreshed is None:
        raise NotFoundError("FeeVariant", variant.id)
    return _fee_variant_to_response(refreshed)


async def update_fee_variant(
    db: AsyncSession, variant_id: int, data: FeeVariantUpdate, *, updated_by: int
) -> FeeVariantResponse:
    variant = await repo.get_fee_variant_by_id(db, variant_id)
    if variant is None:
        raise NotFoundError("FeeVariant", variant_id)
    changes = data.model_dump(exclude_none=True, mode="json")
    if not changes:
        return _fee_variant_to_response(variant)
    async with db.begin_nested():
        await repo.update_fee_variant(db, variant, **changes)
        await audit_log(
            db,
            entity_type="fee_variant",
            action=AuditAction.UPDATE,
            user_id=updated_by,
            entity_id=variant_id,
            new_values=changes,
        )
    await db.commit()
    refreshed = await repo.get_fee_variant_by_id(db, variant_id)
    if refreshed is None:
        raise NotFoundError("FeeVariant", variant_id)
    return _fee_variant_to_response(refreshed)


async def delete_fee_variant(
    db: AsyncSession, variant_id: int, *, deleted_by: int
) -> None:
    variant = await repo.get_fee_variant_by_id(db, variant_id)
    if variant is None:
        raise NotFoundError("FeeVariant", variant_id)
    async with db.begin_nested():
        await repo.delete_fee_variant(db, variant)
        await audit_log(
            db,
            entity_type="fee_variant",
            action=AuditAction.DELETE,
            user_id=deleted_by,
            entity_id=variant_id,
        )
    await db.commit()
