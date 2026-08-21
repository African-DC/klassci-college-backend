"""Ce qu'une famille a versé — sur une vraie base, avec le vrai SQL.

Le scénario qui casse tient en deux gestes du secrétariat. Une famille verse
25 000 sur l'Inscription. L'école lui accorde ensuite une bourse et exonère
l'Inscription. Le montant attendu baisse de 25 000 ; un « déjà versé » calculé
en sommant `Payment.amount` ne bouge pas. La famille paraît en avance de
25 000 sur une scolarité qu'elle n'a jamais payée, l'échéancier cesse de la
signaler en retard, et c'est cet échéancier qui commande la retenue des
documents administratifs.

Les tests tournent sur SQLite via le module standard, comme
`test_enrollment_fees` : ils exécutent le vrai SQL, sans base MySQL à
provisionner.
"""

from collections.abc import Iterator
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import Integer, MetaData, Table, create_engine, func, select
from sqlalchemy.orm import Session

from app.core.database import Base
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
from app.models.installment import FeeInstallment
from app.repositories import installment_repository
from app.services import fees_paid
from app.services.installments import resolve_schedule

AY = 2026
INSCRIPTION = 500  # inscription de l'élève, pas le frais du même nom
CAT_INSCRIPTION = 100
CAT_SCOLARITE_T1 = 101
CAT_COGES = 102
VAR_INSCRIPTION = 200
VAR_SCOLARITE_T1 = 201
VAR_COGES = 202
FRAIS_INSCRIPTION = 300
FRAIS_SCOLARITE_T1 = 301
FRAIS_COGES = 302

_TABLES = (
    "enrollments",
    "enrollment_fees",
    "fee_categories",
    "fee_variants",
    "payments",
    "payment_allocations",
    "fee_installments",
    "enrollment_installments",
)


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
        self._session.flush()


def _sqlite_schema() -> list[Table]:
    """Le schéma transposé pour SQLite, sur une copie jamais partagée.

    SQLite ne numérote automatiquement que les colonnes « INTEGER PRIMARY
    KEY » : les `BIGINT` du modèle refuseraient tout INSERT sans identifiant.
    """
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
    """Une inscription, trois frais, aucun versement encore."""
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
                FeeCategory(id=CAT_INSCRIPTION, name="Inscription", is_mandatory=True),
                FeeCategory(id=CAT_SCOLARITE_T1, name="Scolarite T1", is_mandatory=True),
                FeeCategory(id=CAT_COGES, name="COGES", is_mandatory=False),
                FeeVariant(
                    id=VAR_INSCRIPTION,
                    fee_category_id=CAT_INSCRIPTION,
                    academic_year_id=AY,
                    amount=Decimal("25000"),
                ),
                FeeVariant(
                    id=VAR_SCOLARITE_T1,
                    fee_category_id=CAT_SCOLARITE_T1,
                    academic_year_id=AY,
                    amount=Decimal("25000"),
                ),
                FeeVariant(
                    id=VAR_COGES,
                    fee_category_id=CAT_COGES,
                    academic_year_id=AY,
                    amount=Decimal("10000"),
                ),
                EnrollmentFee(
                    id=FRAIS_INSCRIPTION,
                    enrollment_id=INSCRIPTION,
                    fee_variant_id=VAR_INSCRIPTION,
                    amount=Decimal("25000"),
                    status=EnrollmentFeeStatus.PENDING,
                ),
                EnrollmentFee(
                    id=FRAIS_SCOLARITE_T1,
                    enrollment_id=INSCRIPTION,
                    fee_variant_id=VAR_SCOLARITE_T1,
                    amount=Decimal("25000"),
                    status=EnrollmentFeeStatus.PENDING,
                ),
                EnrollmentFee(
                    id=FRAIS_COGES,
                    enrollment_id=INSCRIPTION,
                    fee_variant_id=VAR_COGES,
                    amount=Decimal("10000"),
                    status=EnrollmentFeeStatus.PENDING,
                ),
            ]
        )
        session.flush()
        yield _AsyncBridge(session)

    engine.dispose()


def _verse(
    bridge: _AsyncBridge,
    montant: str,
    *,
    sur: int,
    statut: PaymentStatus = PaymentStatus.COMPLETED,
    payment_id: int = 1,
) -> None:
    """Un versement à la caisse, imputé sur un frais."""
    session = bridge._session
    session.add(
        Payment(
            id=payment_id,
            enrollment_id=INSCRIPTION,
            amount=Decimal(montant),
            method=PaymentMethod.CASH,
            status=statut,
        )
    )
    session.flush()
    session.add(
        PaymentAllocation(payment_id=payment_id, enrollment_fee_id=sur, amount=Decimal(montant))
    )
    session.flush()


def _somme_brute_des_versements(bridge: _AsyncBridge) -> Decimal:
    """Le calcul qu'on vient de supprimer, gardé ici comme témoin."""
    return Decimal(
        str(
            bridge._session.execute(
                select(func.coalesce(func.sum(Payment.amount), 0)).where(
                    Payment.enrollment_id == INSCRIPTION,
                    Payment.status == PaymentStatus.COMPLETED.value,
                )
            ).scalar_one()
        )
    )


# ---------------------------------------------------------------------------
# Le périmètre du calcul
# ---------------------------------------------------------------------------


async def test_ce_qui_est_verse_sur_un_frais_obligatoire_est_compte(
    db: _AsyncBridge,
) -> None:
    _verse(db, "25000", sur=FRAIS_INSCRIPTION)
    assert await fees_paid.paid_on_mandatory(db, INSCRIPTION) == Decimal("25000.00")  # type: ignore[arg-type]


async def test_ce_qui_est_verse_sur_un_frais_optionnel_reste_dehors(
    db: _AsyncBridge,
) -> None:
    """Le COGES n'est pas dû par tout le monde : il n'entre ni dans ce qui est
    attendu, ni dans ce qui est versé. Le compter d'un seul côté fausserait
    le solde."""
    _verse(db, "10000", sur=FRAIS_COGES)
    assert await fees_paid.paid_on_mandatory(db, INSCRIPTION) == Decimal("0")  # type: ignore[arg-type]


async def test_un_versement_annule_ne_compte_pas(db: _AsyncBridge) -> None:
    _verse(db, "25000", sur=FRAIS_INSCRIPTION, statut=PaymentStatus.CANCELLED)
    assert await fees_paid.paid_on_mandatory(db, INSCRIPTION) == Decimal("0")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# La bourse — le scénario qui a motivé le regroupement
# ---------------------------------------------------------------------------


async def test_une_exoneration_retire_l_argent_qui_lui_etait_impute(
    db: _AsyncBridge,
) -> None:
    """La famille verse 25 000 sur l'Inscription, puis l'école l'exonère.

    Attendu et versé doivent baisser ensemble. Sinon la famille paraît en
    avance de 25 000 sur une scolarité qu'elle n'a jamais payée.
    """
    _verse(db, "25000", sur=FRAIS_INSCRIPTION)
    attendu_avant = await installment_repository.mandatory_total(db, INSCRIPTION)  # type: ignore[arg-type]
    verse_avant = await fees_paid.paid_on_mandatory(db, INSCRIPTION)  # type: ignore[arg-type]
    assert attendu_avant == Decimal("50000.00")
    assert attendu_avant - verse_avant == Decimal("25000.00")

    frais = db._session.get(EnrollmentFee, FRAIS_INSCRIPTION)
    assert frais is not None
    frais.status = EnrollmentFeeStatus.WAIVED
    db._session.flush()

    attendu = await installment_repository.mandatory_total(db, INSCRIPTION)  # type: ignore[arg-type]
    verse = await fees_paid.paid_on_mandatory(db, INSCRIPTION)  # type: ignore[arg-type]

    assert attendu == Decimal("25000.00"), "l'Inscription exonérée n'est plus due"
    assert verse == Decimal("0"), "l'argent imputé à un frais qui n'est plus dû sort du calcul"
    assert attendu - verse == Decimal("25000.00"), "la Scolarité T1 reste entièrement due"

    # Le témoin : la somme brute des versements, elle, n'a pas bougé. C'est
    # exactement ce chiffre qui faisait apparaître la famille en avance.
    assert _somme_brute_des_versements(db) == Decimal("25000.00")


async def test_l_echeancier_signale_toujours_le_retard_apres_une_exoneration(
    db: _AsyncBridge,
) -> None:
    """C'est l'échéancier qui commande la retenue des documents.

    Grille en deux tranches égales, la première échue hier. Après exonération
    de l'Inscription, la famille n'a rien versé sur ce qui reste dû : elle est
    en retard. La somme brute des versements — 25 000 encore comptés —
    couvrait la première tranche et éteignait l'alerte.
    """
    _verse(db, "25000", sur=FRAIS_INSCRIPTION)
    hier = date.today() - timedelta(days=1)
    db._session.add_all(
        [
            FeeInstallment(
                id=1,
                academic_year_id=AY,
                name="1re tranche",
                position=1,
                percentage=Decimal("50"),
                due_date=hier,
            ),
            FeeInstallment(
                id=2,
                academic_year_id=AY,
                name="2e tranche",
                position=2,
                percentage=Decimal("50"),
                due_date=date.today() + timedelta(days=60),
            ),
        ]
    )
    frais = db._session.get(EnrollmentFee, FRAIS_INSCRIPTION)
    assert frais is not None
    frais.status = EnrollmentFeeStatus.WAIVED
    db._session.flush()

    echeancier = await resolve_schedule(db, INSCRIPTION)  # type: ignore[arg-type]

    assert echeancier.total_mandatory == 25000.0
    assert echeancier.total_paid == 0.0
    assert echeancier.is_late is True
    assert echeancier.late_amount == 12500.0
