"""Repository fee — acces DB pour FeeCategory et FeeVariant (CRUD)."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fee import FeeCategory, FeeVariant


# ---------------------------------------------------------------------------
# FeeCategory
# ---------------------------------------------------------------------------


async def get_fee_category_by_id(
    db: AsyncSession, category_id: int
) -> FeeCategory | None:
    stmt = select(FeeCategory).where(FeeCategory.id == category_id)
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_fee_categories(
    db: AsyncSession,
    *,
    page: int = 1,
    size: int = 20,
) -> tuple[list[FeeCategory], int]:
    base = select(FeeCategory)
    count_stmt = select(func.count()).select_from(base.subquery())
    total: int = (await db.execute(count_stmt)).scalar() or 0
    stmt = base.offset((page - 1) * size).limit(size).order_by(FeeCategory.id.desc())
    rows = (await db.execute(stmt)).scalars().all()
    return list(rows), total


async def create_fee_category(db: AsyncSession, **kwargs: object) -> FeeCategory:
    category = FeeCategory(**kwargs)
    db.add(category)
    await db.flush()
    return category


async def update_fee_category(
    db: AsyncSession, category: FeeCategory, **kwargs: object
) -> FeeCategory:
    for key, value in kwargs.items():
        if value is not None:
            setattr(category, key, value)
    await db.flush()
    return category


async def delete_fee_category(db: AsyncSession, category: FeeCategory) -> None:
    await db.delete(category)
    await db.flush()


# ---------------------------------------------------------------------------
# FeeVariant
# ---------------------------------------------------------------------------


async def get_fee_variant_by_id(
    db: AsyncSession, variant_id: int
) -> FeeVariant | None:
    stmt = select(FeeVariant).where(FeeVariant.id == variant_id)
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_fee_variants(
    db: AsyncSession,
    *,
    page: int = 1,
    size: int = 20,
    category_id: int | None = None,
    level_id: int | None = None,
    academic_year_id: int | None = None,
) -> tuple[list[FeeVariant], int]:
    base = select(FeeVariant)
    if category_id is not None:
        base = base.where(FeeVariant.fee_category_id == category_id)
    if level_id is not None:
        base = base.where(FeeVariant.level_id == level_id)
    if academic_year_id is not None:
        base = base.where(FeeVariant.academic_year_id == academic_year_id)
    count_stmt = select(func.count()).select_from(base.subquery())
    total: int = (await db.execute(count_stmt)).scalar() or 0
    stmt = base.offset((page - 1) * size).limit(size).order_by(FeeVariant.id.desc())
    rows = (await db.execute(stmt)).scalars().all()
    return list(rows), total


async def create_fee_variant(db: AsyncSession, **kwargs: object) -> FeeVariant:
    variant = FeeVariant(**kwargs)
    db.add(variant)
    await db.flush()
    return variant


async def update_fee_variant(
    db: AsyncSession, variant: FeeVariant, **kwargs: object
) -> FeeVariant:
    for key, value in kwargs.items():
        if value is not None:
            setattr(variant, key, value)
    await db.flush()
    return variant


async def delete_fee_variant(db: AsyncSession, variant: FeeVariant) -> None:
    await db.delete(variant)
    await db.flush()
