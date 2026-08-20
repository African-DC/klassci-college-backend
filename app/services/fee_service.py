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
    OptionalFeeOptionCreate,
    OptionalFeeOptionListResponse,
    OptionalFeeOptionResponse,
    OptionalFeeOptionUpdate,
)
from app.services.deletion import DeletionPlan, Dependent, ensure_deletable

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
    db: AsyncSession, category_id: int, *, deleted_by: int, cascade: bool = False
) -> None:
    """Supprime une categorie de frais, et refuse clairement si elle sert.

    Sans ce controle, SQLAlchemy tente de detacher les variantes en mettant
    leur categorie a NULL — ce que la colonne interdit — et l'utilisateur
    recoit une erreur de base de donnees illisible. Or la vraie reponse est
    metier : cette categorie porte encore des montants, on ne peut pas la
    faire disparaitre sans decider de leur sort.
    """
    category = await repo.get_fee_category_by_id(db, category_id)
    if category is None:
        raise NotFoundError("FeeCategory", category_id)

    plan = DeletionPlan(
        entity_label=f"« {category.name} »",
        dependents=(
            Dependent(
                "versement imputé",
                "versements imputés",
                await repo.count_paid_allocations_for_category(db, category_id),
                blocking=True,
            ),
            Dependent(
                "montant configuré",
                "montants configurés",
                await repo.count_fee_variants_for_category(db, category_id),
            ),
            Dependent(
                "frais d'élève",
                "frais d'élèves",
                await repo.count_enrollment_fees_for_category(db, category_id),
            ),
            Dependent(
                "option",
                "options",
                await repo.count_options_for_category(db, category_id),
            ),
        ),
    )
    ensure_deletable(plan, cascade=cascade)

    async with db.begin_nested():
        if plan.collateral:
            await repo.cascade_delete_fee_category(db, category_id)
        else:
            await repo.delete_fee_category(db, category)
        await audit_log(
            db,
            entity_type="fee_category",
            action=AuditAction.DELETE,
            user_id=deleted_by,
            entity_id=category_id,
            old_values={"name": category.name},
            new_values={"cascade": bool(plan.collateral), "emporte": plan.as_payload()},
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


async def delete_fee_variant(db: AsyncSession, variant_id: int, *, deleted_by: int) -> None:
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


# ---------------------------------------------------------------------------
# OptionalFeeOption
# ---------------------------------------------------------------------------


def _fee_option_to_response(o: object) -> OptionalFeeOptionResponse:
    return OptionalFeeOptionResponse.model_validate(o)


async def list_optional_fee_options(
    db: AsyncSession,
    *,
    page: int = 1,
    size: int = 20,
    category_id: int | None = None,
    academic_year_id: int | None = None,
) -> OptionalFeeOptionListResponse:
    options, total = await repo.list_optional_fee_options(
        db,
        page=page,
        size=size,
        category_id=category_id,
        academic_year_id=academic_year_id,
    )
    return OptionalFeeOptionListResponse(
        items=[_fee_option_to_response(o) for o in options],
        total=total,
        page=page,
        size=size,
    )


async def get_optional_fee_option(db: AsyncSession, option_id: int) -> OptionalFeeOptionResponse:
    option = await repo.get_optional_fee_option_by_id(db, option_id)
    if option is None:
        raise NotFoundError("OptionalFeeOption", option_id)
    return _fee_option_to_response(option)


async def create_optional_fee_option(
    db: AsyncSession, data: OptionalFeeOptionCreate, *, created_by: int
) -> OptionalFeeOptionResponse:
    async with db.begin_nested():
        option = await repo.create_optional_fee_option(db, **data.model_dump())
        await audit_log(
            db,
            entity_type="optional_fee_option",
            action=AuditAction.CREATE,
            user_id=created_by,
            entity_id=option.id,
            new_values=data.model_dump(mode="json"),
        )
    await db.commit()
    refreshed = await repo.get_optional_fee_option_by_id(db, option.id)
    if refreshed is None:
        raise NotFoundError("OptionalFeeOption", option.id)
    return _fee_option_to_response(refreshed)


async def update_optional_fee_option(
    db: AsyncSession, option_id: int, data: OptionalFeeOptionUpdate, *, updated_by: int
) -> OptionalFeeOptionResponse:
    option = await repo.get_optional_fee_option_by_id(db, option_id)
    if option is None:
        raise NotFoundError("OptionalFeeOption", option_id)
    changes = data.model_dump(exclude_none=True, mode="json")
    if not changes:
        return _fee_option_to_response(option)
    async with db.begin_nested():
        await repo.update_optional_fee_option(db, option, **changes)
        await audit_log(
            db,
            entity_type="optional_fee_option",
            action=AuditAction.UPDATE,
            user_id=updated_by,
            entity_id=option_id,
            new_values=changes,
        )
    await db.commit()
    refreshed = await repo.get_optional_fee_option_by_id(db, option_id)
    if refreshed is None:
        raise NotFoundError("OptionalFeeOption", option_id)
    return _fee_option_to_response(refreshed)


async def delete_optional_fee_option(db: AsyncSession, option_id: int, *, deleted_by: int) -> None:
    option = await repo.get_optional_fee_option_by_id(db, option_id)
    if option is None:
        raise NotFoundError("OptionalFeeOption", option_id)
    async with db.begin_nested():
        await repo.delete_optional_fee_option(db, option)
        await audit_log(
            db,
            entity_type="optional_fee_option",
            action=AuditAction.DELETE,
            user_id=deleted_by,
            entity_id=option_id,
        )
    await db.commit()
