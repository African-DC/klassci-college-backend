"""Annuler un versement rend exactement ce qu'il avait pris.

Le test qui manquait. La réversibilité ne tient pas parce que les allocations
seraient supprimées — elles survivent, c'est l'historique de la famille — mais
parce que tous les totaux joignent `Payment` et filtrent sur `completed`. C'est
un invariant que rien n'empêche de casser : il suffit qu'un jour quelqu'un
écrive une requête sur les allocations sans ce filtre.

Ces tests exécutent la vraie annulation sur une vraie base, et vérifient le
solde après coup plutôt que la forme du code.
"""

from collections.abc import Iterator
from decimal import Decimal

import pytest
from sqlalchemy import Integer, MetaData, Table, create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models.fee import (
    EnrollmentFee,
    EnrollmentFeeStatus,
    Payment,
    PaymentAllocation,
    PaymentStatus,
)
from app.services import fees_paid
from app.services.payments._allocation import recompute_fee_status

INSCRIPTION = 1
FRAIS_T1 = 10
FRAIS_COGES = 11
VERSEMENT = 100


class _AsyncBridge:
    """Donne l'allure d'une `AsyncSession` à une session synchrone."""

    def __init__(self, session: Session) -> None:
        self._session = session

    async def execute(self, statement: object) -> object:
        return self._session.execute(statement)  # type: ignore[arg-type]

    def add(self, instance: object) -> None:
        self._session.add(instance)

    async def flush(self) -> None:
        self._session.flush()

    async def commit(self) -> None:
        self._session.commit()


def _sqlite_schema() -> list[Table]:
    miroir = MetaData()
    for table in Base.metadata.tables.values():
        table.to_metadata(miroir)
    tables = []
    for nom in ("enrollment_fees", "payments", "payment_allocations"):
        t = miroir.tables[nom]
        t.c.id.type = Integer()
        tables.append(t)
    return tables


@pytest.fixture
def db() -> Iterator[_AsyncBridge]:
    """Une inscription qui doit 50 000 en deux frais, soldée par un versement."""
    engine = create_engine("sqlite://")
    for table in _sqlite_schema():
        table.create(engine)

    with Session(engine) as session:
        session.add_all(
            [
                EnrollmentFee(
                    id=FRAIS_T1,
                    enrollment_id=INSCRIPTION,
                    fee_variant_id=1,
                    fee_category_id=1,
                    amount=Decimal("40000"),
                    status=EnrollmentFeeStatus.PENDING.value,
                ),
                EnrollmentFee(
                    id=FRAIS_COGES,
                    enrollment_id=INSCRIPTION,
                    fee_variant_id=2,
                    fee_category_id=2,
                    amount=Decimal("10000"),
                    status=EnrollmentFeeStatus.PENDING.value,
                ),
                Payment(
                    id=VERSEMENT,
                    enrollment_id=INSCRIPTION,
                    amount=Decimal("50000"),
                    method="cash",
                    status=PaymentStatus.COMPLETED.value,
                ),
                PaymentAllocation(
                    id=1,
                    payment_id=VERSEMENT,
                    enrollment_fee_id=FRAIS_T1,
                    amount=Decimal("40000"),
                ),
                PaymentAllocation(
                    id=2,
                    payment_id=VERSEMENT,
                    enrollment_fee_id=FRAIS_COGES,
                    amount=Decimal("10000"),
                ),
            ]
        )
        session.commit()
        yield _AsyncBridge(session)


async def _solder(db: _AsyncBridge) -> None:
    """Applique les statuts que la création du versement aurait posés."""
    verses = await fees_paid.paid_by_enrollment(db, INSCRIPTION)  # type: ignore[arg-type]
    for fee_id in (FRAIS_T1, FRAIS_COGES):
        fee = db._session.get(EnrollmentFee, fee_id)  # noqa: SLF001
        assert fee is not None
        recompute_fee_status(fee, verses.get(fee_id, Decimal("0")))
    await db.commit()


@pytest.mark.asyncio
async def test_avant_annulation_tout_est_solde(db: _AsyncBridge) -> None:
    await _solder(db)
    verses = await fees_paid.paid_by_enrollment(db, INSCRIPTION)  # type: ignore[arg-type]
    assert verses == {FRAIS_T1: Decimal("40000"), FRAIS_COGES: Decimal("10000")}
    for fee_id in (FRAIS_T1, FRAIS_COGES):
        assert db._session.get(EnrollmentFee, fee_id).status == EnrollmentFeeStatus.PAID.value  # noqa: SLF001


@pytest.mark.asyncio
async def test_le_solde_revient_exactement_a_zero(db: _AsyncBridge) -> None:
    """Le geste que la fonctionnalité existe pour permettre."""
    await _solder(db)

    paiement = db._session.get(Payment, VERSEMENT)  # noqa: SLF001
    assert paiement is not None
    paiement.status = PaymentStatus.CANCELLED.value
    await db.commit()
    await _solder(db)

    verses = await fees_paid.paid_by_enrollment(db, INSCRIPTION)  # type: ignore[arg-type]
    assert verses == {}, "un versement annulé compte encore dans le solde"
    for fee_id in (FRAIS_T1, FRAIS_COGES):
        fee = db._session.get(EnrollmentFee, fee_id)  # noqa: SLF001
        assert fee.status == EnrollmentFeeStatus.PENDING.value


@pytest.mark.asyncio
async def test_les_allocations_survivent_a_l_annulation(db: _AsyncBridge) -> None:
    """Elles restent : c'est l'historique que le guichet montre à la famille.

    Si elles disparaissaient, la réversibilité tiendrait à leur suppression au
    lieu de tenir au filtre sur le statut — et ce test dirait le contraire de
    ce que la docstring promet.
    """
    paiement = db._session.get(Payment, VERSEMENT)  # noqa: SLF001
    paiement.status = PaymentStatus.CANCELLED.value
    await db.commit()

    par_frais = await fees_paid.payments_by_enrollment_fee(db, INSCRIPTION)  # type: ignore[arg-type]
    lignes = par_frais.get(FRAIS_T1, [])
    assert len(lignes) == 1, "l'historique du frais a perdu son versement annulé"
    versement, part = lignes[0]
    assert part == Decimal("40000")
    assert versement.status == PaymentStatus.CANCELLED.value


@pytest.mark.asyncio
async def test_un_frais_exonere_ne_redevient_pas_du(db: _AsyncBridge) -> None:
    """`WAIVED` est collant : une annulation ne ressuscite pas une dette remise."""
    fee = db._session.get(EnrollmentFee, FRAIS_COGES)  # noqa: SLF001
    fee.status = EnrollmentFeeStatus.WAIVED.value
    await db.commit()

    recompute_fee_status(fee, Decimal("0"))
    assert fee.status == EnrollmentFeeStatus.WAIVED.value
