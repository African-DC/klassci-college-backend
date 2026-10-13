"""Un versement d'une autre année ne gonfle pas le journal de celle-ci.

En production, l'année courante 2026-2027 affichait aussi les 4 millions
encaissés sur 2025-2026 : la liste n'avait pas d'année, le bandeau non plus,
et « Collecté » additionnait les deux exercices. Le filet interroge la vraie
agrégation, pas la signature.
"""

from collections.abc import Iterator
from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import BigInteger, create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models.academic import AcademicYear, Class, Level
from app.models.enrollment import Enrollment
from app.models.fee import Payment
from app.models.user import Student
from app.repositories import payment_repository as repo
from app.repositories.payment_filters import PaymentFilters
from app.services.payments import query

CAISSIERE = 7
ANNEE_COURANTE = 1
ANNEE_PRECEDENTE = 5


class _Pont:
    def __init__(self, session: Session) -> None:
        self._session = session

    async def execute(self, statement: object) -> object:
        return self._session.execute(statement)  # type: ignore[arg-type]


def _versement(
    pid: int, inscription: int | None, montant: str, *, recu: datetime | None = None
) -> Payment:
    return Payment(
        id=pid,
        enrollment_id=inscription,
        amount=Decimal(montant),
        method="cash",
        status="completed",
        received_by=CAISSIERE,
        created_at=recu or datetime(2026, 10, 1, 10, 0, 0),
    )


@pytest.fixture()
def db() -> Iterator[Session]:
    moteur = create_engine("sqlite://")

    @compiles(BigInteger, "sqlite")
    def _bigint(type_, compiler, **kw):  # noqa: ARG001
        return "INTEGER"

    Base.metadata.create_all(moteur)
    with Session(moteur) as session:
        session.add_all(
            [
                AcademicYear(
                    id=ANNEE_COURANTE,
                    name="2026-2027",
                    start_date=date(2026, 9, 14),
                    end_date=date(2027, 7, 30),
                    is_current=True,
                ),
                AcademicYear(
                    id=ANNEE_PRECEDENTE,
                    name="2025-2026",
                    start_date=date(2025, 9, 8),
                    end_date=date(2026, 6, 30),
                    is_current=False,
                ),
                Level(id=1, name="6eme"),
                Class(id=1, name="6eme A", level_id=1),
                Student(
                    id=1,
                    last_name="KOUASSI",
                    first_name="Aya",
                    last_name_key="KOUASSI",
                    first_name_key="AYA",
                ),
                Enrollment(id=10, student_id=1, class_id=1, academic_year_id=ANNEE_COURANTE),
                Enrollment(id=11, student_id=1, class_id=1, academic_year_id=ANNEE_PRECEDENTE),
                _versement(1, 10, "50000"),
                _versement(2, 11, "40000"),
                _versement(3, None, "1000", recu=datetime(2026, 11, 12, 16, 0, 0)),
            ]
        )
        session.flush()
        yield session


@pytest.mark.asyncio
async def test_la_liste_d_une_annee_ignore_l_inscription_de_l_autre(db: Session) -> None:
    lignes, total = await repo.list_payments(
        _Pont(db), filters=PaymentFilters(academic_year_id=ANNEE_COURANTE), page=1, size=20
    )
    assert total == 2
    assert {p.id for p in lignes} == {1, 3}


@pytest.mark.asyncio
async def test_changer_d_annee_montre_l_autre_exercice(db: Session) -> None:
    lignes, total = await repo.list_payments(
        _Pont(db), filters=PaymentFilters(academic_year_id=ANNEE_PRECEDENTE), page=1, size=20
    )
    assert total == 1
    assert lignes[0].id == 2


@pytest.mark.asyncio
async def test_sans_annee_le_journal_additionne_encore_les_exercices(db: Session) -> None:
    """Le serveur n'invente pas l'année : c'est l'écran qui la pose.

    Sans paramètre, le comportement historique reste — tous les versements.
    L'écran des paiements envoie désormais l'année courante, et c'est ce
    filet qui empêche d'oublier de la poser d'un côté et pas de l'autre.
    """
    _lignes, total = await repo.list_payments(_Pont(db), filters=PaymentFilters(), page=1, size=20)
    assert total == 3


@pytest.mark.asyncio
async def test_le_bandeau_cloisonne_ne_compte_pas_l_autre_annee(db: Session) -> None:
    recap = await query.get_payments_summary(
        _Pont(db),
        academic_year_id=ANNEE_COURANTE,
        received_by=CAISSIERE,
    )
    assert recap.payment_count == 2
    assert recap.total_paid == 51000.0


@pytest.mark.asyncio
async def test_l_orphelin_hors_bornes_ne_passe_pas_par_la_date(db: Session) -> None:
    recap = await query.get_payments_summary(
        _Pont(db),
        academic_year_id=ANNEE_PRECEDENTE,
        received_by=CAISSIERE,
    )
    assert recap.payment_count == 1
    assert recap.total_paid == 40000.0


@pytest.mark.asyncio
async def test_arrears_are_included_in_daily_collections_regardless_of_year(db: Session) -> None:
    period = PaymentFilters(
        date_from=datetime(2026, 10, 1, 0, 0),
        date_to=datetime(2026, 10, 1, 23, 59, 59),
    )
    entries, count = await repo.list_payments(_Pont(db), filters=period, page=1, size=20)
    summary = await query.get_payments_summary(_Pont(db), received_by=CAISSIERE, filters=period)
    assert count == summary.payment_count == 2
    assert {payment.id for payment in entries} == {1, 2}
    assert summary.total_collected == 90000.0


@pytest.mark.asyncio
async def test_collected_total_obeys_school_year_and_history_scope(db: Session) -> None:
    current = await query.get_payments_summary(
        _Pont(db), received_by=CAISSIERE, filters=PaymentFilters(academic_year_id=ANNEE_COURANTE)
    )
    history = await query.get_payments_summary(_Pont(db), received_by=CAISSIERE)
    assert current.total_collected == 51000.0
    assert history.total_collected == 91000.0


@pytest.mark.asyncio
async def test_week_collections_include_previous_year_arrears(db: Session) -> None:
    week = PaymentFilters(
        date_from=datetime(2026, 9, 28, 0, 0),
        date_to=datetime(2026, 10, 4, 23, 59, 59),
    )
    summary = await query.get_payments_summary(_Pont(db), received_by=CAISSIERE, filters=week)
    assert summary.payment_count == 2
    assert summary.total_collected == 90000.0


@pytest.mark.asyncio
async def test_global_history_cash_kpi_preserves_legacy_recovery(db: Session) -> None:
    summary = await query.get_payments_summary(_Pont(db), filters=PaymentFilters())
    # Existing API consumers still receive the historical all-year recovery totals.
    assert summary.total_expected is not None
    assert summary.total_collected == 91000.0
    assert summary.payment_count == 3


@pytest.mark.asyncio
async def test_strict_year_only_counts_linked_enrollments(db: Session) -> None:
    """Daily cash keeps arrears and orphan payments; school-year cash does not."""
    period = PaymentFilters(academic_year_id=ANNEE_COURANTE, linked_year_only=True)
    payments, count = await repo.list_payments(
        _Pont(db), filters=period, page=1, size=20
    )
    summary = await query.get_payments_summary(
        _Pont(db), received_by=CAISSIERE, filters=period
    )
    assert {payment.id for payment in payments} == {1}
    assert count == summary.payment_count == 1
    assert summary.total_collected == 50000.0


@pytest.mark.asyncio
async def test_strict_year_does_not_claim_an_orphan(db: Session) -> None:
    previous = PaymentFilters(academic_year_id=ANNEE_PRECEDENTE, linked_year_only=True)
    payments, count = await repo.list_payments(
        _Pont(db), filters=previous, page=1, size=20
    )
    assert count == 1
    assert {payment.id for payment in payments} == {2}
