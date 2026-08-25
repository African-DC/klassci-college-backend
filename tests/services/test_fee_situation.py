"""La situation financière du reçu dit la même chose que `fees_paid`.

Le reçu que la famille emporte annonce un reste à payer. Si ce chiffre se
calcule ailleurs que dans la vérité du projet sur ce qui a été versé, il finira
par contredire la fiche de l'élève et le portail de la famille — le projet a
déjà connu cinq formules concurrentes pour « combien a été payé ».

Ces tests comparent donc, sur une vraie base et avec le vrai SQL, ce que rend
`fee_situation` à ce que rend `fees_paid`. Ils tournent sur SQLite via le module
standard, comme `test_paid_on_mandatory`.
"""

from collections.abc import Iterator
from decimal import Decimal

import pytest
from sqlalchemy import Integer, MetaData, Table, create_engine
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
from app.services import fee_situation, fees_paid

AY = 2026
INSCRIPTION = 500  # l'inscription de l'élève, pas le frais du même nom

# Catégories dans l'ordre où la caisse impute : Inscription, T1, T2, COGES.
CATEGORIES = [
    (100, "Inscription", 10, True),
    (101, "Scolarité T1", 20, True),
    (102, "Scolarité T2", 30, True),
    (103, "COGES", 50, False),
]
# frais : (id, category_id, montant)
FRAIS = [
    (300, 100, "37000"),
    (301, 101, "55000"),
    (302, 102, "55000"),
    (303, 103, "10000"),
]

_TABLES = (
    "enrollments",
    "enrollment_fees",
    "fee_categories",
    "fee_variants",
    "payments",
    "payment_allocations",
)


class _AsyncBridge:
    """Donne l'allure d'une `AsyncSession` à une session synchrone."""

    def __init__(self, session: Session) -> None:
        self._session = session

    async def execute(self, statement: object) -> object:
        return self._session.execute(statement)  # type: ignore[arg-type]


def _sqlite_schema() -> list[Table]:
    """Le schéma transposé pour SQLite, sur une copie jamais partagée."""
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
    """Une inscription, quatre frais, aucun versement encore."""
    engine = create_engine("sqlite://")
    for table in _sqlite_schema():
        table.create(engine)

    with Session(engine) as session:
        session.add(
            Enrollment(
                id=INSCRIPTION,
                student_id=1,
                class_id=1,
                academic_year_id=AY,
                status=EnrollmentStatus.VALIDE,
            )
        )
        for cat_id, nom, priorite, obligatoire in CATEGORIES:
            session.add(
                FeeCategory(id=cat_id, name=nom, priority=priorite, is_mandatory=obligatoire)
            )
        for fee_id, cat_id, montant in FRAIS:
            session.add(
                FeeVariant(
                    id=fee_id + 1000,
                    fee_category_id=cat_id,
                    academic_year_id=AY,
                    amount=Decimal(montant),
                )
            )
            session.add(
                EnrollmentFee(
                    id=fee_id,
                    enrollment_id=INSCRIPTION,
                    fee_variant_id=fee_id + 1000,
                    fee_category_id=cat_id,
                    amount=Decimal(montant),
                    status=EnrollmentFeeStatus.PENDING,
                )
            )
        session.flush()
        yield _AsyncBridge(session)

    engine.dispose()


def _verse(
    bridge: _AsyncBridge,
    montant: str,
    *,
    sur: int,
    payment_id: int,
    statut: PaymentStatus = PaymentStatus.COMPLETED,
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


# ---------------------------------------------------------------------------
# La correspondance avec fees_paid
# ---------------------------------------------------------------------------


async def test_le_verse_de_chaque_frais_vient_de_fees_paid(db: _AsyncBridge):
    _verse(db, "37000", sur=300, payment_id=1)
    _verse(db, "13000", sur=301, payment_id=2)

    verse_par_frais = await fees_paid.paid_by_enrollment(db, INSCRIPTION)
    situation = await fee_situation.load_situation(db, INSCRIPTION)

    par_id = dict(zip([f[0] for f in FRAIS], situation.lines, strict=True))
    for fee_id, ligne in par_id.items():
        assert ligne.paid == verse_par_frais.get(fee_id, Decimal("0"))

    assert situation.total_paid == sum(verse_par_frais.values())


async def test_les_totaux_se_recoupent(db: _AsyncBridge):
    _verse(db, "37000", sur=300, payment_id=1)
    _verse(db, "13000", sur=301, payment_id=2)

    situation = await fee_situation.load_situation(db, INSCRIPTION)

    assert situation.total_due == Decimal("157000")
    assert situation.total_paid == Decimal("50000")
    assert situation.total_remaining == Decimal("107000")
    assert situation.total_remaining == situation.total_due - situation.total_paid


async def test_quinze_versements_ne_font_pas_quinze_lignes(db: _AsyncBridge):
    """Le tableau est borné par les frais, pas par le nombre de versements."""
    for i in range(1, 16):
        _verse(db, "1000", sur=301, payment_id=i)

    situation = await fee_situation.load_situation(db, INSCRIPTION)

    assert len(situation.lines) == len(FRAIS)
    assert situation.total_paid == Decimal("15000")
    verse_par_frais = await fees_paid.paid_by_enrollment(db, INSCRIPTION)
    assert verse_par_frais[301] == Decimal("15000")


async def test_un_versement_en_attente_ne_compte_pas_encore(db: _AsyncBridge):
    """Même périmètre que `fees_paid` : seuls les encaissements comptent."""
    _verse(db, "37000", sur=300, payment_id=1, statut=PaymentStatus.PENDING)

    situation = await fee_situation.load_situation(db, INSCRIPTION)
    verse_par_frais = await fees_paid.paid_by_enrollment(db, INSCRIPTION)

    assert verse_par_frais == {}
    assert situation.total_paid == Decimal("0")
    assert situation.total_remaining == situation.total_due


async def test_un_trop_percu_ne_produit_pas_un_reste_negatif(db: _AsyncBridge):
    """« Il vous reste -5 000 F » n'est pas une phrase à tendre au guichet."""
    _verse(db, "42000", sur=300, payment_id=1)

    situation = await fee_situation.load_situation(db, INSCRIPTION)
    inscription = next(line for line in situation.lines if line.category_name == "Inscription")

    assert inscription.paid == Decimal("42000")
    assert inscription.remaining == Decimal("0")
    assert situation.total_remaining >= Decimal("0")


async def test_les_frais_sortent_dans_l_ordre_d_imputation(db: _AsyncBridge):
    """L'ordre du reçu est celui de la caisse : Inscription, puis trimestres."""
    situation = await fee_situation.load_situation(db, INSCRIPTION)

    assert [line.category_name for line in situation.lines] == [
        "Inscription",
        "Scolarité T1",
        "Scolarité T2",
        "COGES",
    ]


async def test_une_inscription_sans_frais_donne_une_situation_vide(db: _AsyncBridge):
    situation = await fee_situation.load_situation(db, 999)

    assert situation.lines == ()
    assert situation.total_due == Decimal("0")
    assert situation.total_remaining == Decimal("0")
    assert situation.completion_rate == 0.0
