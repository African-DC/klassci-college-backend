"""Requêtes du suivi consolidé des échéanciers, exécutées sur une vraie base.

`test_installment_overview.py` vérifie la logique de retard avec des
dépôts simulés. Ce fichier exécute les requêtes elles-mêmes : un regroupement
mal posé, un frais facultatif compté ou un versement annulé pris pour un
encaissement donneraient un solde faux à toute une école sans qu'aucun test
de logique ne le voie.
"""

from collections.abc import Iterator
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import BigInteger, create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

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
from app.models.user import Student
from app.repositories import installment_overview_repository as repo

ANNEE = 1


class _Pont:
    """Allure d'une `AsyncSession` pour une session synchrone : seul `execute` sert."""

    def __init__(self, session: Session) -> None:
        self._session = session

    async def execute(self, statement: object) -> object:
        return self._session.execute(statement)  # type: ignore[arg-type]


@pytest.fixture()
def db() -> Iterator[Session]:
    moteur = create_engine("sqlite://")

    @compiles(BigInteger, "sqlite")
    def _bigint(type_, compiler, **kw):  # noqa: ARG001
        return "INTEGER"

    Base.metadata.create_all(moteur)
    with Session(moteur) as s:
        s.add_all(
            [
                AcademicYear(
                    id=ANNEE,
                    name="2025-2026",
                    start_date=date(2025, 9, 8),
                    end_date=date(2026, 6, 30),
                    is_current=True,
                ),
                Level(id=1, name="6eme"),
                Class(id=1, name="6eme A", level_id=1),
                Class(id=2, name="5eme A", level_id=1),
                FeeCategory(id=1, name="Scolarite", priority=1, is_mandatory=True),
                FeeCategory(id=2, name="Tenue", priority=6, is_mandatory=False),
                FeeCategory(id=3, name="COGES", priority=5, is_mandatory=True),
                FeeVariant(id=1, fee_category_id=1, academic_year_id=ANNEE, amount=Decimal("0")),
                FeeVariant(id=2, fee_category_id=2, academic_year_id=ANNEE, amount=Decimal("0")),
                FeeVariant(id=3, fee_category_id=3, academic_year_id=ANNEE, amount=Decimal("0")),
                Student(id=1, last_name="KOUASSI", first_name="Aya", enrollment_number="CI-001"),
                Student(id=2, last_name="TRAORÉ", first_name="Ibrahim", enrollment_number="CI-002"),
                Student(id=3, last_name="YAO", first_name="Adjoua", enrollment_number="CI-003"),
            ]
        )
        s.flush()
        s.add_all(
            [
                Enrollment(
                    id=10,
                    student_id=1,
                    class_id=1,
                    academic_year_id=ANNEE,
                    status=EnrollmentStatus.VALIDE.value,
                ),
                Enrollment(
                    id=20,
                    student_id=2,
                    class_id=2,
                    academic_year_id=ANNEE,
                    status=EnrollmentStatus.VALIDE.value,
                ),
                Enrollment(
                    id=30,
                    student_id=3,
                    class_id=1,
                    academic_year_id=ANNEE,
                    status=EnrollmentStatus.REJETE.value,
                ),
            ]
        )
        s.flush()
        s.add_all(
            [
                # Aya : 100 000 obligatoires + 15 000 de tenue facultative + 20 000 exonérés.
                EnrollmentFee(
                    id=1,
                    enrollment_id=10,
                    fee_variant_id=1,
                    fee_category_id=1,
                    amount=Decimal("100000"),
                    status=EnrollmentFeeStatus.PARTIAL.value,
                ),
                EnrollmentFee(
                    id=2,
                    enrollment_id=10,
                    fee_variant_id=2,
                    fee_category_id=2,
                    amount=Decimal("15000"),
                    status=EnrollmentFeeStatus.PENDING.value,
                ),
                EnrollmentFee(
                    id=3,
                    enrollment_id=10,
                    fee_variant_id=3,
                    fee_category_id=3,
                    amount=Decimal("20000"),
                    status=EnrollmentFeeStatus.WAIVED.value,
                ),
                # Ibrahim : 80 000 obligatoires.
                EnrollmentFee(
                    id=4,
                    enrollment_id=20,
                    fee_variant_id=1,
                    fee_category_id=1,
                    amount=Decimal("80000"),
                    status=EnrollmentFeeStatus.PENDING.value,
                ),
            ]
        )
        s.flush()
        s.add_all(
            [
                Payment(
                    id=1,
                    enrollment_id=10,
                    amount=Decimal("30000"),
                    method=PaymentMethod.CASH.value,
                    status=PaymentStatus.COMPLETED.value,
                ),
                Payment(
                    id=2,
                    enrollment_id=10,
                    amount=Decimal("50000"),
                    method=PaymentMethod.CASH.value,
                    status=PaymentStatus.CANCELLED.value,
                ),
                Payment(
                    id=3,
                    enrollment_id=10,
                    amount=Decimal("15000"),
                    method=PaymentMethod.CASH.value,
                    status=PaymentStatus.COMPLETED.value,
                ),
            ]
        )
        s.flush()
        s.add_all(
            [
                PaymentAllocation(id=1, payment_id=1, enrollment_fee_id=1, amount=Decimal("30000")),
                PaymentAllocation(id=2, payment_id=2, enrollment_fee_id=1, amount=Decimal("50000")),
                PaymentAllocation(id=3, payment_id=3, enrollment_fee_id=2, amount=Decimal("15000")),
            ]
        )
        s.commit()
        yield s


@pytest.mark.asyncio
async def test_totals_keep_only_mandatory_unwaived_fees(db: Session) -> None:
    totals = await repo.mandatory_totals(_Pont(db), [10, 20])

    assert totals == {10: Decimal("100000"), 20: Decimal("80000")}


@pytest.mark.asyncio
async def test_paid_ignores_cancelled_payments_and_optional_fees(db: Session) -> None:
    paid = await repo.mandatory_paid(_Pont(db), [10, 20])

    # 30 000 encaissés sur la scolarité ; le versement annulé et la tenue ne comptent pas.
    assert paid == {10: Decimal("30000")}


@pytest.mark.asyncio
async def test_identities_skip_closed_enrollments_and_filter_by_class(db: Session) -> None:
    toutes = await repo.list_identities(_Pont(db), academic_year_id=ANNEE)
    sixieme = await repo.list_identities(_Pont(db), academic_year_id=ANNEE, class_id=1)

    assert [x.enrollment_id for x in toutes] == [20, 10]  # tri par classe, puis par nom
    assert [x.enrollment_id for x in sixieme] == [10]


@pytest.mark.asyncio
async def test_search_matches_names_without_accents_and_matricules(db: Session) -> None:
    par_nom = await repo.list_identities(_Pont(db), academic_year_id=ANNEE, search="traore")
    par_matricule = await repo.list_identities(_Pont(db), academic_year_id=ANNEE, search="CI-001")
    joker = await repo.list_identities(_Pont(db), academic_year_id=ANNEE, search="%")

    assert [x.enrollment_id for x in par_nom] == [20]
    assert [x.enrollment_id for x in par_matricule] == [10]
    assert joker == []  # un « % » saisi est cherché tel quel, pas comme joker
