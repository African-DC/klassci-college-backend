"""Repository fee — acces DB pour FeeCategory et FeeVariant (CRUD)."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fee import FeeCategory, FeeVariant, OptionalFeeOption

# ---------------------------------------------------------------------------
# FeeCategory
# ---------------------------------------------------------------------------


async def get_fee_category_by_id(db: AsyncSession, category_id: int) -> FeeCategory | None:
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


async def get_fee_variant_by_id(db: AsyncSession, variant_id: int) -> FeeVariant | None:
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


async def update_fee_variant(db: AsyncSession, variant: FeeVariant, **kwargs: object) -> FeeVariant:
    for key, value in kwargs.items():
        if value is not None:
            setattr(variant, key, value)
    await db.flush()
    return variant


async def delete_fee_variant(db: AsyncSession, variant: FeeVariant) -> None:
    await db.delete(variant)
    await db.flush()


# ---------------------------------------------------------------------------
# OptionalFeeOption
# ---------------------------------------------------------------------------


async def get_optional_fee_option_by_id(
    db: AsyncSession, option_id: int
) -> OptionalFeeOption | None:
    stmt = select(OptionalFeeOption).where(OptionalFeeOption.id == option_id)
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_optional_fee_options(
    db: AsyncSession,
    *,
    page: int = 1,
    size: int = 20,
    category_id: int | None = None,
    academic_year_id: int | None = None,
) -> tuple[list[OptionalFeeOption], int]:
    base = select(OptionalFeeOption)
    if category_id is not None:
        base = base.where(OptionalFeeOption.fee_category_id == category_id)
    if academic_year_id is not None:
        base = base.where(OptionalFeeOption.academic_year_id == academic_year_id)
    count_stmt = select(func.count()).select_from(base.subquery())
    total: int = (await db.execute(count_stmt)).scalar() or 0
    stmt = base.offset((page - 1) * size).limit(size).order_by(OptionalFeeOption.id.desc())
    rows = (await db.execute(stmt)).scalars().all()
    return list(rows), total


async def create_optional_fee_option(db: AsyncSession, **kwargs: object) -> OptionalFeeOption:
    option = OptionalFeeOption(**kwargs)
    db.add(option)
    await db.flush()
    return option


async def update_optional_fee_option(
    db: AsyncSession, option: OptionalFeeOption, **kwargs: object
) -> OptionalFeeOption:
    for key, value in kwargs.items():
        if value is not None:
            setattr(option, key, value)
    await db.flush()
    return option


async def delete_optional_fee_option(db: AsyncSession, option: OptionalFeeOption) -> None:
    await db.delete(option)
    await db.flush()


async def count_fee_variants_for_category(db: AsyncSession, category_id: int) -> int:
    """Nombre de montants encore rattachés à une catégorie.

    Sert à refuser une suppression avec un message qui dit combien, plutôt
    que de laisser la base répondre à notre place.
    """
    stmt = (
        select(func.count())
        .select_from(FeeVariant)
        .where(FeeVariant.fee_category_id == category_id)
    )
    return int((await db.execute(stmt)).scalar_one())


async def count_paid_allocations_for_category(db: AsyncSession, category_id: int) -> int:
    """Versements déjà imputés sur les frais issus de cette catégorie.

    C'est le compteur qui interdit la suppression : de l'argent encaissé qui
    perd sa contrepartie ne se rattrape pas.
    """
    from app.models.fee import EnrollmentFee, PaymentAllocation

    stmt = (
        select(func.count())
        .select_from(PaymentAllocation)
        .join(EnrollmentFee, EnrollmentFee.id == PaymentAllocation.enrollment_fee_id)
        .join(FeeVariant, FeeVariant.id == EnrollmentFee.fee_variant_id)
        .where(FeeVariant.fee_category_id == category_id)
    )
    return int((await db.execute(stmt)).scalar_one())


async def count_enrollment_fees_for_category(db: AsyncSession, category_id: int) -> int:
    """Frais d'élèves issus de cette catégorie, payés ou non."""
    from app.models.fee import EnrollmentFee

    stmt = (
        select(func.count())
        .select_from(EnrollmentFee)
        .join(FeeVariant, FeeVariant.id == EnrollmentFee.fee_variant_id)
        .where(FeeVariant.fee_category_id == category_id)
    )
    return int((await db.execute(stmt)).scalar_one())


async def count_options_for_category(db: AsyncSession, category_id: int) -> int:
    stmt = (
        select(func.count())
        .select_from(OptionalFeeOption)
        .where(OptionalFeeOption.fee_category_id == category_id)
    )
    return int((await db.execute(stmt)).scalar_one())


async def cascade_delete_fee_category(db: AsyncSession, category_id: int) -> None:
    """Efface la catégorie et tout ce qui en découle, de bas en haut.

    L'ordre suit les dépendances : frais d'élèves, puis options, puis
    montants, puis la catégorie. Appelée seulement après `ensure_deletable`,
    donc jamais sur des frais portant un versement.
    """
    from sqlalchemy import delete

    from app.models.enrollment import StudentOption
    from app.models.fee import EnrollmentFee

    variant_ids = select(FeeVariant.id).where(FeeVariant.fee_category_id == category_id)
    option_ids = select(OptionalFeeOption.id).where(
        OptionalFeeOption.fee_category_id == category_id
    )

    await db.execute(delete(EnrollmentFee).where(EnrollmentFee.fee_variant_id.in_(variant_ids)))
    await db.execute(
        delete(StudentOption).where(StudentOption.optional_fee_option_id.in_(option_ids))
    )
    await db.execute(
        delete(OptionalFeeOption).where(OptionalFeeOption.fee_category_id == category_id)
    )
    await db.execute(delete(FeeVariant).where(FeeVariant.fee_category_id == category_id))
    await db.execute(delete(FeeCategory).where(FeeCategory.id == category_id))
    await db.flush()
