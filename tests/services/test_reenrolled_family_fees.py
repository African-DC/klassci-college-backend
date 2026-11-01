"""Une famille réinscrite retrouve son année en cours, et voit l'an prochain à part.

Constaté sur la démo : Aminata avait versé 142 000 F sur 185 000 F cette année,
et lisait « 35 000 F dus, 0 F payé », les frais de sa réinscription. Ces tests
exécutent les vrais services sur une vraie base, relue dans une session neuve.
"""

from collections.abc import AsyncIterator
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import BigInteger
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.academic import AcademicYear, Class, Level
from app.models.enrollment import Enrollment, EnrollmentStatus
from app.models.fee import (
    EnrollmentFee,
    EnrollmentFeeStatus,
    FeeCategory,
    FeeVariant,
    Payment,
    PaymentAllocation,
    PaymentMethod,
    PaymentStatus,
)
from app.models.user import Parent, ParentStudent, Student
from app.services import parent_portal_service, student_portal_service

# Relative to today: the next year must not have started, whenever this runs.
BASE_YEAR = date.today().year
THIS_YEAR = 1
NEXT_YEAR = 5
YEAR_AFTER = 6
LAST_YEAR = 9
REENROLLED = 102
NOT_REENROLLED = 103
ONLY_NEXT_YEAR = 104
WITH_OLD_DEBT = 106
SKIPPED_THIS_YEAR = 108
TWO_YEARS_AHEAD = 109
STUDENT_USER = 100
PARENT_USER = 200
PARENT = 7


@compiles(BigInteger, "sqlite")
def _bigint(type_, compiler, **kw):  # noqa: ARG001
    return "INTEGER"


def _enrollment(
    id_: int, student: int, year: int, status: EnrollmentStatus, class_id: int
) -> Enrollment:
    return Enrollment(
        id=id_, student_id=student, class_id=class_id, academic_year_id=year, status=status
    )


def _fee(id_: int, enrollment: int, amount: str) -> EnrollmentFee:
    return EnrollmentFee(
        id=id_,
        enrollment_id=enrollment,
        fee_variant_id=1,
        fee_category_id=1,
        amount=Decimal(amount),
        status=EnrollmentFeeStatus.PENDING.value,
    )


def _paid(id_: int, enrollment: int, fee: int, amount: str) -> list[object]:
    return [
        Payment(
            id=id_,
            enrollment_id=enrollment,
            amount=Decimal(amount),
            method=PaymentMethod.CASH.value,
            status=PaymentStatus.COMPLETED.value,
            enrollment_fee_id=None,
        ),
        PaymentAllocation(payment_id=id_, enrollment_fee_id=fee, amount=Decimal(amount)),
    ]


@pytest.fixture
async def factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with maker() as db:
        db.add_all(
            [
                AcademicYear(
                    id=LAST_YEAR,
                    name="2024-2025",
                    start_date=date(BASE_YEAR - 2, 9, 1),
                    end_date=date(BASE_YEAR - 1, 7, 1),
                    is_current=False,
                ),
                AcademicYear(
                    id=THIS_YEAR,
                    name="2025-2026",
                    start_date=date(BASE_YEAR - 1, 9, 1),
                    end_date=date(BASE_YEAR, 7, 1),
                    is_current=True,
                ),
                AcademicYear(
                    id=NEXT_YEAR,
                    name="2026-2027",
                    start_date=date(BASE_YEAR + 1, 9, 1),
                    end_date=date(BASE_YEAR + 2, 7, 1),
                    is_current=False,
                ),
                AcademicYear(
                    id=YEAR_AFTER,
                    name="2027-2028",
                    start_date=date(BASE_YEAR + 2, 9, 1),
                    end_date=date(BASE_YEAR + 3, 7, 1),
                    is_current=False,
                ),
                Level(id=1, name="6eme"),
                Level(id=2, name="5eme"),
                Class(id=10, name="6ème A", level_id=1),
                Class(id=11, name="5ème A", level_id=2),
                FeeCategory(id=1, name="Scolarité", priority=1, is_mandatory=True),
                FeeVariant(
                    id=1, fee_category_id=1, academic_year_id=THIS_YEAR, amount=Decimal("0")
                ),
                Student(
                    id=REENROLLED,
                    user_id=STUDENT_USER,
                    first_name="Aminata",
                    last_name="Traoré",
                    enrollment_number="M2",
                ),
                Student(
                    id=NOT_REENROLLED, first_name="Fatou", last_name="Koné", enrollment_number="M3"
                ),
                Student(
                    id=ONLY_NEXT_YEAR, first_name="Awa", last_name="Bamba", enrollment_number="M4"
                ),
                Student(
                    id=WITH_OLD_DEBT, first_name="Yao", last_name="Aka", enrollment_number="M6"
                ),
                Parent(id=PARENT, user_id=PARENT_USER, first_name="Mariam", last_name="Koné"),
                ParentStudent(
                    parent_id=PARENT, student_id=REENROLLED, relationship_type="guardian"
                ),
                ParentStudent(
                    parent_id=PARENT, student_id=NOT_REENROLLED, relationship_type="guardian"
                ),
                ParentStudent(
                    parent_id=PARENT, student_id=ONLY_NEXT_YEAR, relationship_type="guardian"
                ),
                ParentStudent(
                    parent_id=PARENT, student_id=WITH_OLD_DEBT, relationship_type="guardian"
                ),
                Student(
                    id=SKIPPED_THIS_YEAR, first_name="Awa", last_name="Sy", enrollment_number="M8"
                ),
                Student(
                    id=TWO_YEARS_AHEAD, first_name="Ali", last_name="Ba", enrollment_number="M9"
                ),
                ParentStudent(
                    parent_id=PARENT, student_id=SKIPPED_THIS_YEAR, relationship_type="guardian"
                ),
                ParentStudent(
                    parent_id=PARENT, student_id=TWO_YEARS_AHEAD, relationship_type="guardian"
                ),
                # Inscrit l'an dernier et l'an prochain, mais pas cette année.
                _enrollment(10, SKIPPED_THIS_YEAR, LAST_YEAR, EnrollmentStatus.VALIDE, 10),
                _enrollment(11, SKIPPED_THIS_YEAR, NEXT_YEAR, EnrollmentStatus.PROSPECT, 11),
                _fee(10, 10, "20000"),
                _fee(11, 11, "35000"),
                # Cette année, l'an prochain et l'année d'après.
                _enrollment(12, TWO_YEARS_AHEAD, THIS_YEAR, EnrollmentStatus.VALIDE, 10),
                _enrollment(13, TWO_YEARS_AHEAD, YEAR_AFTER, EnrollmentStatus.PROSPECT, 11),
                _enrollment(14, TWO_YEARS_AHEAD, NEXT_YEAR, EnrollmentStatus.PROSPECT, 11),
                _fee(12, 12, "50000"),
                _fee(13, 13, "10000"),
                _fee(14, 14, "35000"),
                # 185 000 dus et 142 000 versés cette année, 35 000 dus l'an prochain.
                _enrollment(1, REENROLLED, THIS_YEAR, EnrollmentStatus.VALIDE, 10),
                _enrollment(777, REENROLLED, NEXT_YEAR, EnrollmentStatus.PROSPECT, 11),
                _fee(1, 1, "185000"),
                _fee(2, 777, "35000"),
                *_paid(1, 1, 1, "142000"),
                _enrollment(2, NOT_REENROLLED, THIS_YEAR, EnrollmentStatus.VALIDE, 10),
                _fee(3, 2, "50000"),
                _enrollment(3, ONLY_NEXT_YEAR, NEXT_YEAR, EnrollmentStatus.PROSPECT, 11),
                _fee(4, 3, "35000"),
                # 20 000 restent de l'an dernier, à côté de cette année et de l'an prochain.
                _enrollment(4, WITH_OLD_DEBT, LAST_YEAR, EnrollmentStatus.VALIDE, 10),
                _enrollment(5, WITH_OLD_DEBT, THIS_YEAR, EnrollmentStatus.VALIDE, 11),
                _enrollment(6, WITH_OLD_DEBT, NEXT_YEAR, EnrollmentStatus.PROSPECT, 11),
                _fee(5, 4, "20000"),
                _fee(6, 5, "60000"),
                _fee(7, 6, "35000"),
            ]
        )
        await db.commit()
    yield maker
    await engine.dispose()


@pytest.mark.asyncio
async def test_a_reenrolled_student_sees_this_years_money(factory) -> None:
    async with factory() as db:
        fees = await student_portal_service.get_fees(db, STUDENT_USER)

    assert (fees.total_due, fees.total_paid, fees.balance) == (
        Decimal("185000"),
        Decimal("142000"),
        Decimal("43000"),
    )
    assert len(fees.upcoming) == 1
    line = fees.upcoming[0]
    assert line.academic_year_name == "2026-2027"
    assert line.class_name == "5ème A"
    assert (line.total_due, line.total_paid, line.remaining) == (
        Decimal("35000"),
        Decimal("0"),
        Decimal("35000"),
    )


@pytest.mark.asyncio
async def test_the_profile_shows_the_current_class_and_year(factory) -> None:
    async with factory() as db:
        profile = await student_portal_service.get_profile(db, STUDENT_USER)

    assert profile.class_name == "6ème A"
    assert profile.academic_year_name == "2025-2026"


@pytest.mark.asyncio
async def test_the_student_home_shows_the_current_class_and_balance(factory) -> None:
    async with factory() as db:
        home = await student_portal_service.get_dashboard(db, STUDENT_USER)

    assert home.class_name == "6ème A"
    assert home.fees_remaining == 43000.0


@pytest.mark.asyncio
async def test_a_parent_sees_this_year_and_next_year_apart(factory) -> None:
    async with factory() as db:
        fees = await parent_portal_service.get_child_fees(db, PARENT_USER, REENROLLED)

    assert (fees.total_due, fees.total_paid) == (Decimal("185000"), Decimal("142000"))
    assert [line.remaining for line in fees.upcoming] == [Decimal("35000")]
    # Ni ce qui reste de cette année, ni la réinscription : aucune dette passée.
    assert fees.fees_arrears_other_years == Decimal("0")
    assert fees.has_arrears_other_years is False


@pytest.mark.asyncio
async def test_a_real_debt_from_last_year_stays_visible_on_its_own(factory) -> None:
    async with factory() as db:
        fees = await parent_portal_service.get_child_fees(db, PARENT_USER, WITH_OLD_DEBT)

    assert fees.total_due == Decimal("60000")
    assert fees.fees_arrears_other_years == Decimal("20000")
    assert [line.total_due for line in fees.upcoming] == [Decimal("35000")]


@pytest.mark.asyncio
async def test_the_parent_lists_show_the_current_class(factory) -> None:
    async with factory() as db:
        children = await parent_portal_service.list_children(db, PARENT_USER)
        home = await parent_portal_service.get_dashboard(db, PARENT_USER)

    listed = {c.id: c.enrollment for c in children.children}
    assert listed[REENROLLED].class_name == "6ème A"
    assert listed[REENROLLED].academic_year_name == "2025-2026"
    summary = {c.id: c for c in home.children}
    assert summary[REENROLLED].class_name == "6ème A"
    assert summary[REENROLLED].fees_remaining == 43000.0


@pytest.mark.asyncio
async def test_a_family_not_reenrolled_has_nothing_upcoming(factory) -> None:
    async with factory() as db:
        fees = await parent_portal_service.get_child_fees(db, PARENT_USER, NOT_REENROLLED)

    assert fees.total_due == Decimal("50000")
    assert fees.upcoming == []


@pytest.mark.asyncio
async def test_a_student_only_enrolled_for_next_year_keeps_that_enrollment(factory) -> None:
    async with factory() as db:
        fees = await parent_portal_service.get_child_fees(db, PARENT_USER, ONLY_NEXT_YEAR)

    assert fees.total_due == Decimal("35000")
    assert fees.upcoming == []


@pytest.mark.asyncio
async def test_a_year_that_has_not_started_never_replaces_the_last_one(factory) -> None:
    async with factory() as db:
        fees = await parent_portal_service.get_child_fees(db, PARENT_USER, SKIPPED_THIS_YEAR)

    assert fees.total_due == Decimal("20000")
    assert [line.academic_year_name for line in fees.upcoming] == ["2026-2027"]
    assert fees.fees_arrears_other_years == Decimal("0")


@pytest.mark.asyncio
async def test_no_future_year_counts_as_arrears(factory) -> None:
    async with factory() as db:
        fees = await parent_portal_service.get_child_fees(db, PARENT_USER, TWO_YEARS_AHEAD)

    assert fees.total_due == Decimal("50000")
    # Chaque année à venir a sa ligne, la plus proche d'abord : aucun montant ne disparaît.
    assert [(line.academic_year_name, line.remaining) for line in fees.upcoming] == [
        ("2026-2027", Decimal("35000")),
        ("2027-2028", Decimal("10000")),
    ]
    assert fees.fees_arrears_other_years == Decimal("0")
