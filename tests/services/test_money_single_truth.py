"""Un même franc CFA ne peut pas valoir deux montants selon l'écran.

Trois formules coexistaient pour dire « combien a été versé ». Celle de
`fees_paid`, une copie frais par frais dans le dépôt des paiements, et une
troisième au tableau de bord qui sommait les versements bruts face à un
attendu qui totalisait tous les frais — facultatifs et exonérés compris.

Le scénario qui casse : la famille verse 25 000 sur l'Inscription, l'école lui
accorde ensuite une bourse et exonère l'Inscription. Sur la fiche de l'élève,
attendu et versé baissent ensemble. Au tableau de bord, l'attendu baissait et
le versé restait : l'école se croyait payée d'une dette qu'elle venait
d'annuler.

Les tests tournent sur SQLite via le module standard, comme
`test_paid_on_mandatory` : ils exécutent le vrai SQL.
"""

from collections.abc import Iterator
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import Integer, MetaData, Table, create_engine, func, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models.academic import AcademicYear
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
from app.services import fees_paid
from app.services.payments._allocation import paid_for_fees, recompute_fee_status
from app.services.payments.query import get_payments_summary

AY = 2026
INSCRIPTION = 500
CAT_INSCRIPTION, CAT_SCOLARITE_T1, CAT_COGES = 100, 101, 102
VAR_INSCRIPTION, VAR_SCOLARITE_T1, VAR_COGES = 200, 201, 202
FRAIS_INSCRIPTION, FRAIS_SCOLARITE_T1, FRAIS_COGES = 300, 301, 302

_TABLES = (
    "academic_years",
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

    def add(self, instance: object) -> None:
        self._session.add(instance)

    async def flush(self) -> None:
        self._session.flush()

    async def commit(self) -> None:
        self._session.flush()


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
    """Une inscription, deux frais obligatoires, un facultatif, rien de versé."""
    engine = create_engine("sqlite://")
    for table in _sqlite_schema():
        table.create(engine)

    with Session(engine) as session:
        session.add_all(
            [
                AcademicYear(
                    id=AY,
                    name="2025-2026",
                    start_date=date(2025, 9, 1),
                    end_date=date(2026, 7, 31),
                    is_current=True,
                ),
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
                    fee_category_id=CAT_INSCRIPTION,
                    amount=Decimal("25000"),
                    status=EnrollmentFeeStatus.PENDING,
                ),
                EnrollmentFee(
                    id=FRAIS_SCOLARITE_T1,
                    enrollment_id=INSCRIPTION,
                    fee_variant_id=VAR_SCOLARITE_T1,
                    fee_category_id=CAT_SCOLARITE_T1,
                    amount=Decimal("25000"),
                    status=EnrollmentFeeStatus.PENDING,
                ),
                EnrollmentFee(
                    id=FRAIS_COGES,
                    enrollment_id=INSCRIPTION,
                    fee_variant_id=VAR_COGES,
                    fee_category_id=CAT_COGES,
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
            created_at=date(2026, 1, 12),
        )
    )
    session.flush()
    session.add(
        PaymentAllocation(payment_id=payment_id, enrollment_fee_id=sur, amount=Decimal(montant))
    )
    session.flush()


def _exonere(bridge: _AsyncBridge, frais_id: int) -> None:
    frais = bridge._session.get(EnrollmentFee, frais_id)
    assert frais is not None
    frais.status = EnrollmentFeeStatus.WAIVED
    bridge._session.flush()


def _somme_brute_des_versements(bridge: _AsyncBridge) -> Decimal:
    """L'ancienne formule du tableau de bord, gardée ici comme témoin."""
    return Decimal(
        str(
            bridge._session.execute(
                select(func.coalesce(func.sum(Payment.amount), 0)).where(
                    Payment.status == PaymentStatus.COMPLETED.value
                )
            ).scalar_one()
        )
    )


# ---------------------------------------------------------------------------
# Le type du montant
# ---------------------------------------------------------------------------


async def test_le_montant_verse_est_rendu_en_decimal(db: _AsyncBridge) -> None:
    """Des francs CFA en flottant, c'est un arrondi qui attend son heure — et
    chaque appelant devait recharger le montant avant de le soustraire."""
    _verse(db, "10000", sur=FRAIS_INSCRIPTION)

    par_frais = await fees_paid.paid_by_enrollment(db, INSCRIPTION)  # type: ignore[arg-type]
    assert par_frais[FRAIS_INSCRIPTION] == Decimal("10000.00")
    assert all(isinstance(m, Decimal) for m in par_frais.values())

    par_eleve = await fees_paid.paid_by_enrollment_fee(db, 1)  # type: ignore[arg-type]
    assert all(isinstance(m, Decimal) for m in par_eleve.values())
    # Le montant se soustrait directement d'un montant de frais, sans détour.
    frais = db._session.get(EnrollmentFee, FRAIS_INSCRIPTION)
    assert frais is not None
    assert frais.amount - par_frais[FRAIS_INSCRIPTION] == Decimal("15000.00")


async def test_un_frais_sans_versement_ne_figure_pas_dans_le_releve(
    db: _AsyncBridge,
) -> None:
    """L'appelant retombe sur zéro : c'est ce que fait chaque `.get(id, 0)`."""
    _verse(db, "10000", sur=FRAIS_INSCRIPTION)
    par_frais = await fees_paid.paid_by_enrollment(db, INSCRIPTION)  # type: ignore[arg-type]
    assert FRAIS_SCOLARITE_T1 not in par_frais


# ---------------------------------------------------------------------------
# Le relevé groupé remplace les boucles frais par frais
# ---------------------------------------------------------------------------


async def test_le_releve_groupe_couvre_tous_les_frais_touches(db: _AsyncBridge) -> None:
    """Une requête pour l'inscription entière, pas une par frais : c'est le
    chemin de la caisse, celui qu'on emprunte le tiroir ouvert."""
    _verse(db, "25000", sur=FRAIS_INSCRIPTION, payment_id=1)
    _verse(db, "10000", sur=FRAIS_SCOLARITE_T1, payment_id=2)

    frais = [
        db._session.get(EnrollmentFee, FRAIS_INSCRIPTION),
        db._session.get(EnrollmentFee, FRAIS_SCOLARITE_T1),
    ]
    verses = await paid_for_fees(db, [f for f in frais if f is not None])  # type: ignore[arg-type]

    assert verses[FRAIS_INSCRIPTION] == Decimal("25000.00")
    assert verses[FRAIS_SCOLARITE_T1] == Decimal("10000.00")


async def test_le_statut_du_frais_suit_ce_qui_y_est_impute(db: _AsyncBridge) -> None:
    """Soldé quand la somme couvre le frais, partiel en dessous."""
    _verse(db, "25000", sur=FRAIS_INSCRIPTION, payment_id=1)
    _verse(db, "10000", sur=FRAIS_SCOLARITE_T1, payment_id=2)

    inscription = db._session.get(EnrollmentFee, FRAIS_INSCRIPTION)
    scolarite = db._session.get(EnrollmentFee, FRAIS_SCOLARITE_T1)
    assert inscription is not None and scolarite is not None

    verses = await paid_for_fees(db, [inscription, scolarite])  # type: ignore[arg-type]
    recompute_fee_status(inscription, verses.get(inscription.id, Decimal("0")))
    recompute_fee_status(scolarite, verses.get(scolarite.id, Decimal("0")))

    assert inscription.status == EnrollmentFeeStatus.PAID.value
    assert scolarite.status == EnrollmentFeeStatus.PARTIAL.value


async def test_un_frais_exonere_garde_son_statut(db: _AsyncBridge) -> None:
    """Une bourse ne se défait pas parce qu'un versement passe à côté."""
    _exonere(db, FRAIS_INSCRIPTION)
    frais = db._session.get(EnrollmentFee, FRAIS_INSCRIPTION)
    assert frais is not None

    recompute_fee_status(frais, Decimal("25000"))
    assert frais.status == EnrollmentFeeStatus.WAIVED


# ---------------------------------------------------------------------------
# Le tableau de bord lit la même dette que la fiche de l'élève
# ---------------------------------------------------------------------------


async def test_le_frais_facultatif_reste_hors_du_taux_d_avancement(
    db: _AsyncBridge,
) -> None:
    """Le COGES n'est pas dû par tout le monde : le compter d'un seul côté
    ferait apparaître l'école en avance sur une dette qui n'existe pas."""
    _verse(db, "10000", sur=FRAIS_COGES)

    resume = await get_payments_summary(db, academic_year_id=AY)  # type: ignore[arg-type]

    assert resume.total_expected == 50000.0, "seuls les deux frais obligatoires sont dus"
    assert resume.total_paid == 0.0
    assert resume.completion_rate == 0.0
    # Le témoin : l'ancienne formule comptait ces 10 000 comme un encaissement
    # sur la scolarité.
    assert _somme_brute_des_versements(db) == Decimal("10000.00")


async def test_une_exoneration_retire_l_argent_qui_lui_etait_impute(
    db: _AsyncBridge,
) -> None:
    """Attendu et versé doivent baisser ensemble, au tableau de bord comme sur
    la fiche de l'élève."""
    _verse(db, "25000", sur=FRAIS_INSCRIPTION)

    avant = await get_payments_summary(db, academic_year_id=AY)  # type: ignore[arg-type]
    assert (avant.total_expected, avant.total_paid) == (50000.0, 25000.0)
    assert avant.completion_rate == 50.0

    _exonere(db, FRAIS_INSCRIPTION)

    apres = await get_payments_summary(db, academic_year_id=AY)  # type: ignore[arg-type]
    assert apres.total_expected == 25000.0, "l'Inscription exonérée n'est plus due"
    assert apres.total_paid == 0.0, "l'argent imputé à un frais annulé sort du calcul"
    assert apres.completion_rate == 0.0, "la Scolarité T1 reste entièrement à payer"

    # Le témoin : la somme brute des versements n'a pas bougé. C'est elle qui
    # affichait 100 % de recouvrement sur une école qui n'avait rien encaissé
    # de ce qu'elle attend encore.
    assert _somme_brute_des_versements(db) == Decimal("25000.00")


async def test_le_tableau_de_bord_dit_la_meme_chose_que_la_fiche_de_l_eleve(
    db: _AsyncBridge,
) -> None:
    """Un caissier et un directeur qui regardent le même établissement ne
    doivent pas lire deux montants différents."""
    _verse(db, "25000", sur=FRAIS_INSCRIPTION)
    _exonere(db, FRAIS_INSCRIPTION)

    resume = await get_payments_summary(db, academic_year_id=AY)  # type: ignore[arg-type]
    fiche = await fees_paid.paid_on_mandatory(db, INSCRIPTION)  # type: ignore[arg-type]

    assert Decimal(str(resume.total_paid)) == fiche


async def test_un_versement_annule_ne_compte_pas_comme_encaisse(
    db: _AsyncBridge,
) -> None:
    _verse(db, "25000", sur=FRAIS_INSCRIPTION, statut=PaymentStatus.CANCELLED)

    resume = await get_payments_summary(db, academic_year_id=AY)  # type: ignore[arg-type]
    assert resume.total_paid == 0.0
    assert resume.total_cancelled == 25000.0


async def test_sans_annee_precisee_le_resume_couvre_tout(db: _AsyncBridge) -> None:
    """L'écran d'accueil n'a pas toujours une année sous la main."""
    _verse(db, "25000", sur=FRAIS_INSCRIPTION)

    resume = await get_payments_summary(db)  # type: ignore[arg-type]
    assert resume.total_expected == 50000.0
    assert resume.total_paid == 25000.0
