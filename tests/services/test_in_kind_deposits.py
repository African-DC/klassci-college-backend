"""Fournitures en nature : déposé → plus dû ; non déposé → frais encaissable.

Un dépôt n'est pas une exonération : fees_waived et le recouvrement cash
ignorent `in_kind`. Les tests tournent sur SQLite, comme
`test_paid_on_mandatory`.
"""

from collections.abc import Iterator
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import Integer, MetaData, Table, create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.core.exceptions import ConflictError
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
from app.repositories import installment_repository
from app.schemas.enrollment import InKindDeposit
from app.services import enrollment_fees, fee_propagation, fees_paid

AY = 2026
INSCRIPTION = 500
CAT_RAMETTE = 100
CAT_CHEMISE = 101
CAT_SCOLARITE = 102
CAT_POLO = 103
VAR_RAMETTE = 200
VAR_CHEMISE = 201
VAR_SCOLARITE = 202
VAR_POLO = 203
FRAIS_RAMETTE = 300
FRAIS_CHEMISE = 301
FRAIS_SCOLARITE = 302
FRAIS_POLO = 303

_TABLES = (
    "enrollments",
    "enrollment_fees",
    "fee_categories",
    "fee_variants",
    "payments",
    "payment_allocations",
)


class _AsyncBridge:
    def __init__(self, session: Session) -> None:
        self._session = session

    async def execute(self, statement: object) -> object:
        return self._session.execute(statement)  # type: ignore[arg-type]

    def add(self, instance: object) -> None:
        self._session.add(instance)

    async def flush(self) -> None:
        self._session.flush()

    async def delete(self, instance: object) -> None:
        self._session.delete(instance)


def _sqlite_schema() -> list[Table]:
    miroir = MetaData()
    for table in Base.metadata.tables.values():
        table.to_metadata(miroir)

    tables = []
    for nom in _TABLES:
        table = miroir.tables[nom]
        table.c.id.type = Integer()
        tables.append(table)
    return tables


@pytest.fixture
def db() -> Iterator[_AsyncBridge]:
    engine = create_engine("sqlite://")
    for table in _sqlite_schema():
        table.create(engine)

    with Session(engine) as session:
        session.add_all(
            [
                Enrollment(
                    id=INSCRIPTION,
                    student_id=1,
                    class_id=1,
                    academic_year_id=AY,
                    status=EnrollmentStatus.VALIDE,
                ),
                FeeCategory(
                    id=CAT_RAMETTE,
                    name="Ramette",
                    is_mandatory=True,
                    accepts_in_kind=True,
                ),
                FeeCategory(
                    id=CAT_CHEMISE,
                    name="Chemise cartonnée",
                    is_mandatory=True,
                    accepts_in_kind=True,
                ),
                FeeCategory(
                    id=CAT_SCOLARITE,
                    name="Scolarite T1",
                    is_mandatory=True,
                    accepts_in_kind=False,
                ),
                FeeCategory(
                    id=CAT_POLO,
                    name="Tenue",
                    is_mandatory=True,
                    accepts_in_kind=False,
                    entitlements=[{"label": "Polo", "quantity": 1, "kind": "item"}],
                ),
                FeeVariant(
                    id=VAR_RAMETTE,
                    fee_category_id=CAT_RAMETTE,
                    academic_year_id=AY,
                    amount=Decimal("2500"),
                ),
                FeeVariant(
                    id=VAR_CHEMISE,
                    fee_category_id=CAT_CHEMISE,
                    academic_year_id=AY,
                    amount=Decimal("1000"),
                ),
                FeeVariant(
                    id=VAR_SCOLARITE,
                    fee_category_id=CAT_SCOLARITE,
                    academic_year_id=AY,
                    amount=Decimal("25000"),
                ),
                FeeVariant(
                    id=VAR_POLO,
                    fee_category_id=CAT_POLO,
                    academic_year_id=AY,
                    amount=Decimal("15000"),
                ),
                EnrollmentFee(
                    id=FRAIS_RAMETTE,
                    enrollment_id=INSCRIPTION,
                    fee_variant_id=VAR_RAMETTE,
                    fee_category_id=CAT_RAMETTE,
                    amount=Decimal("2500"),
                    status=EnrollmentFeeStatus.PENDING,
                ),
                EnrollmentFee(
                    id=FRAIS_CHEMISE,
                    enrollment_id=INSCRIPTION,
                    fee_variant_id=VAR_CHEMISE,
                    fee_category_id=CAT_CHEMISE,
                    amount=Decimal("1000"),
                    status=EnrollmentFeeStatus.PENDING,
                ),
                EnrollmentFee(
                    id=FRAIS_SCOLARITE,
                    enrollment_id=INSCRIPTION,
                    fee_variant_id=VAR_SCOLARITE,
                    fee_category_id=CAT_SCOLARITE,
                    amount=Decimal("25000"),
                    status=EnrollmentFeeStatus.PENDING,
                ),
                EnrollmentFee(
                    id=FRAIS_POLO,
                    enrollment_id=INSCRIPTION,
                    fee_variant_id=VAR_POLO,
                    fee_category_id=CAT_POLO,
                    amount=Decimal("15000"),
                    status=EnrollmentFeeStatus.PENDING,
                ),
            ]
        )
        session.flush()
        yield _AsyncBridge(session)

    engine.dispose()


def _verse(bridge: _AsyncBridge, montant: str, *, sur: int, payment_id: int = 1) -> None:
    session = bridge._session
    session.add(
        Payment(
            id=payment_id,
            enrollment_id=INSCRIPTION,
            amount=Decimal(montant),
            method=PaymentMethod.CASH,
            status=PaymentStatus.COMPLETED,
        )
    )
    session.flush()
    session.add(
        PaymentAllocation(payment_id=payment_id, enrollment_fee_id=sur, amount=Decimal(montant))
    )
    session.flush()


async def test_une_categorie_deposee_l_autre_reste_due(db: _AsyncBridge) -> None:
    """Ramette déposée, chemise non : une ligne in_kind, une pending.
    Le dû cash = montant de la non déposée seulement (plus la scolarité)."""
    await enrollment_fees.apply_in_kind_deposits(
        db,  # type: ignore[arg-type]
        INSCRIPTION,
        [
            InKindDeposit(fee_category_id=CAT_RAMETTE, deposited=True),
            InKindDeposit(fee_category_id=CAT_CHEMISE, deposited=False),
        ],
        deposited_by=1,
    )

    ramette = db._session.get(EnrollmentFee, FRAIS_RAMETTE)
    chemise = db._session.get(EnrollmentFee, FRAIS_CHEMISE)
    assert ramette is not None and chemise is not None
    assert ramette.status == EnrollmentFeeStatus.IN_KIND
    assert chemise.status == EnrollmentFeeStatus.PENDING

    attendu = await installment_repository.mandatory_total(db, INSCRIPTION)  # type: ignore[arg-type]
    assert attendu == Decimal("41000.00")


async def test_depot_tardif_pending_passe_en_in_kind(db: _AsyncBridge) -> None:
    with patch("app.services.enrollment_fees.audit_log", new=AsyncMock()):
        fee = await enrollment_fees.mark_in_kind_deposit(
            db,  # type: ignore[arg-type]
            enrollment_id=INSCRIPTION,
            fee_id=FRAIS_RAMETTE,
            deposited_by=7,
        )
    assert fee.status == EnrollmentFeeStatus.IN_KIND
    assert fee.deposited_by_user_id == 7
    assert fee.deposited_at is not None

    attendu = await installment_repository.mandatory_total(db, INSCRIPTION)  # type: ignore[arg-type]
    assert attendu == Decimal("41000.00")


async def test_depot_tardif_paye_refuse_en_409(db: _AsyncBridge) -> None:
    ramette = db._session.get(EnrollmentFee, FRAIS_RAMETTE)
    assert ramette is not None
    ramette.status = EnrollmentFeeStatus.PAID
    db._session.flush()

    with (
        patch("app.services.enrollment_fees.audit_log", new=AsyncMock()),
        pytest.raises(ConflictError, match="versement"),
    ):
        await enrollment_fees.mark_in_kind_deposit(
            db,  # type: ignore[arg-type]
            enrollment_id=INSCRIPTION,
            fee_id=FRAIS_RAMETTE,
            deposited_by=1,
        )

    assert db._session.get(EnrollmentFee, FRAIS_RAMETTE).status == EnrollmentFeeStatus.PAID


async def test_depot_tardif_avec_allocation_refuse(db: _AsyncBridge) -> None:
    _verse(db, "2500", sur=FRAIS_RAMETTE)

    with (
        patch("app.services.enrollment_fees.audit_log", new=AsyncMock()),
        pytest.raises(ConflictError, match="versement"),
    ):
        await enrollment_fees.mark_in_kind_deposit(
            db,  # type: ignore[arg-type]
            enrollment_id=INSCRIPTION,
            fee_id=FRAIS_RAMETTE,
            deposited_by=1,
        )

    assert db._session.get(EnrollmentFee, FRAIS_RAMETTE).status == EnrollmentFeeStatus.PENDING


async def test_regenerate_conserve_in_kind(db: _AsyncBridge) -> None:
    ramette = db._session.get(EnrollmentFee, FRAIS_RAMETTE)
    assert ramette is not None
    ramette.status = EnrollmentFeeStatus.IN_KIND
    db._session.flush()

    enrollment = db._session.get(Enrollment, INSCRIPTION)
    assert enrollment is not None
    enrollment.enrollment_fees  # noqa: B018 — charge la relation

    with (
        patch(
            "app.services.enrollment_fees.repo.get_enrollment_by_id",
            new=AsyncMock(return_value=enrollment),
        ),
        patch("app.services.enrollment_fees.audit_log", new=AsyncMock()),
        patch(
            "app.services.enrollment_fees.create_mandatory_enrollment_fees",
            new=AsyncMock(),
        ),
        patch(
            "app.services.enrollment_fees.fees_paid.fee_ids_with_allocations",
            new=AsyncMock(return_value=set()),
        ),
    ):
        await enrollment_fees.regenerate_enrollment_fees(
            db,  # type: ignore[arg-type]
            INSCRIPTION,
            regenerated_by=1,
        )

    conservee = db._session.get(EnrollmentFee, FRAIS_RAMETTE)
    assert conservee is not None
    assert conservee.status == EnrollmentFeeStatus.IN_KIND


async def test_un_depot_ne_gonfle_pas_fees_waived_ni_le_recouvrement(
    db: _AsyncBridge,
) -> None:
    ramette = db._session.get(EnrollmentFee, FRAIS_RAMETTE)
    assert ramette is not None
    ramette.status = EnrollmentFeeStatus.IN_KIND
    db._session.flush()

    verse = await fees_paid.paid_on_mandatory(db, INSCRIPTION)  # type: ignore[arg-type]
    assert verse == Decimal("0")

    variant = db._session.get(FeeVariant, VAR_RAMETTE)
    assert variant is not None
    variant.amount = Decimal("3000")
    db._session.flush()

    with patch("app.services.fee_propagation.audit_log", new=AsyncMock()):
        apercu = await fee_propagation.preview_variant_propagation(
            db,  # type: ignore[arg-type]
            VAR_RAMETTE,
        )
    assert apercu.fees_waived == 0


async def test_entitlements_polo_inchanges_par_un_depot(db: _AsyncBridge) -> None:
    polo_cat = db._session.get(FeeCategory, CAT_POLO)
    assert polo_cat is not None
    avant = list(polo_cat.entitlements)

    await enrollment_fees.apply_in_kind_deposits(
        db,  # type: ignore[arg-type]
        INSCRIPTION,
        [InKindDeposit(fee_category_id=CAT_POLO, deposited=True)],
        deposited_by=1,
    )

    polo_cat = db._session.get(FeeCategory, CAT_POLO)
    polo_frais = db._session.get(EnrollmentFee, FRAIS_POLO)
    assert polo_cat is not None and polo_frais is not None
    assert polo_cat.entitlements == avant
    assert polo_frais.status == EnrollmentFeeStatus.PENDING


# ---------------------------------------------------------------------------
# Annuler un dépôt : le geste qui manquait, et sans lequel la saisie en lot
# multiplierait par quarante une erreur qu'on corrigeait à la main en base
# ---------------------------------------------------------------------------


async def test_annuler_un_depot_rend_la_ligne_due(db: _AsyncBridge) -> None:
    """Le dépôt était une erreur : la ligne redevient exactement ce qu'elle était.

    Avant ce geste, un article coché par erreur sortait du dû sans aucun moyen
    d'y revenir depuis l'application. La correction se faisait à la main dans
    la base.
    """
    with patch("app.services.enrollment_fees.audit_log", new=AsyncMock()):
        await enrollment_fees.mark_in_kind_deposit(
            db,  # type: ignore[arg-type]
            enrollment_id=INSCRIPTION,
            fee_id=FRAIS_RAMETTE,
            deposited_by=7,
        )
        fee = await enrollment_fees.cancel_in_kind_deposit(
            db,  # type: ignore[arg-type]
            enrollment_id=INSCRIPTION,
            fee_id=FRAIS_RAMETTE,
            cancelled_by=9,
        )

    assert fee.status == EnrollmentFeeStatus.PENDING
    assert fee.deposited_at is None
    assert fee.deposited_by_user_id is None


async def test_annuler_un_depot_remet_le_montant_dans_le_du(db: _AsyncBridge) -> None:
    """Ce que la famille doit revient à ce qu'elle devait : c'est le seul test
    qui dit que l'annulation défait vraiment quelque chose."""
    avant = await installment_repository.mandatory_total(db, INSCRIPTION)  # type: ignore[arg-type]

    with patch("app.services.enrollment_fees.audit_log", new=AsyncMock()):
        await enrollment_fees.mark_in_kind_deposit(
            db,  # type: ignore[arg-type]
            enrollment_id=INSCRIPTION,
            fee_id=FRAIS_RAMETTE,
            deposited_by=7,
        )
        pendant = await installment_repository.mandatory_total(db, INSCRIPTION)  # type: ignore[arg-type]
        await enrollment_fees.cancel_in_kind_deposit(
            db,  # type: ignore[arg-type]
            enrollment_id=INSCRIPTION,
            fee_id=FRAIS_RAMETTE,
            cancelled_by=9,
        )

    apres = await installment_repository.mandatory_total(db, INSCRIPTION)  # type: ignore[arg-type]
    assert pendant < avant
    assert apres == avant


async def test_annuler_une_ligne_non_deposee_est_refuse(db: _AsyncBridge) -> None:
    """Il n'y a rien à défaire, et prétendre le contraire remettrait une ligne
    payée ou exonérée dans le dû."""
    with (
        patch("app.services.enrollment_fees.audit_log", new=AsyncMock()),
        pytest.raises(ConflictError, match="pas marquée déposée"),
    ):
        await enrollment_fees.cancel_in_kind_deposit(
            db,  # type: ignore[arg-type]
            enrollment_id=INSCRIPTION,
            fee_id=FRAIS_RAMETTE,
            cancelled_by=1,
        )

    assert db._session.get(EnrollmentFee, FRAIS_RAMETTE).status == EnrollmentFeeStatus.PENDING


async def test_annuler_un_depot_portant_un_versement_est_refuse(db: _AsyncBridge) -> None:
    """Un frais déposé ne devrait jamais porter de versement, `plannable_fees`
    l'écarte de toute imputation. Le contrôle est refait quand même : rendre
    « due » une ligne sur laquelle de l'argent a atterri par un chemin qu'on
    n'a pas prévu ferait réapparaître une dette déjà payée."""
    ramette = db._session.get(EnrollmentFee, FRAIS_RAMETTE)
    assert ramette is not None
    ramette.status = EnrollmentFeeStatus.IN_KIND
    db._session.flush()
    _verse(db, "2500", sur=FRAIS_RAMETTE)

    with (
        patch("app.services.enrollment_fees.audit_log", new=AsyncMock()),
        pytest.raises(ConflictError, match="versement"),
    ):
        await enrollment_fees.cancel_in_kind_deposit(
            db,  # type: ignore[arg-type]
            enrollment_id=INSCRIPTION,
            fee_id=FRAIS_RAMETTE,
            cancelled_by=1,
        )

    assert db._session.get(EnrollmentFee, FRAIS_RAMETTE).status == EnrollmentFeeStatus.IN_KIND
