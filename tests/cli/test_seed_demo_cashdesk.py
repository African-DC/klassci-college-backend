"""Le semis n'encaisse que sur une caisse encore ouverte.

L'application refuse d'enregistrer un versement sur une journée déjà clôturée,
et elle a raison : l'écart signé le soir deviendrait faux la seconde suivante.
Un locataire de démonstration déjà présenté porte donc des caisses verrouillées,
arrêtées par leur caissier ou d'office à minuit.

Tant que le semis distribuait ses versements sur tous les comptes de caisse sans
regarder, le premier versement tombant sur un tiroir arrêté interrompait
l'installation entière — après dix minutes de notes et de bulletins déjà écrits.
"""

from collections.abc import Iterator
from datetime import date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import BigInteger, Integer, MetaData, create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401  — enregistre toutes les tables sur `Base`
from app.cli.seed_demo import cashdesk
from app.cli.seed_demo.context import SeedContext
from app.core.database import Base
from app.core.exceptions import BusinessValidationError
from app.models.cash_session import CashSession, CashSessionStatus

CAISSE_A = 55
CAISSE_B = 56
SIGNATAIRE = 1


class _AsyncBridge:
    """Donne l'allure d'une `AsyncSession` à une session synchrone."""

    def __init__(self, session: Session) -> None:
        self.session = session

    async def execute(self, statement: Any) -> Any:
        return self.session.execute(statement)


def _sqlite_schema() -> MetaData:
    miroir = MetaData()
    for table in Base.metadata.tables.values():
        table.to_metadata(miroir)
    for table in miroir.tables.values():
        for column in table.columns:
            if isinstance(column.type, BigInteger):
                column.type = Integer()
    return miroir


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite://")
    _sqlite_schema().create_all(engine)
    with Session(engine) as opened:
        yield opened
    engine.dispose()


def _contexte(session: Session) -> SeedContext:
    ctx = SeedContext(
        db=_AsyncBridge(session),  # type: ignore[arg-type]
        tenant="demo",
        today=date.today(),
        actor_id=SIGNATAIRE,
    )
    ctx.staff_user_by_role = {"cashier2": CAISSE_A, "cashier3": CAISSE_B}
    return ctx


def _journee(session: Session, cashier: int, status: CashSessionStatus, when: date) -> None:
    session.add(
        CashSession(
            cashier_user_id=cashier,
            business_date=when,
            status=status,
            opened_at=datetime.combine(when, datetime.min.time()),
        )
    )
    session.flush()


@pytest.mark.asyncio
async def test_sans_aucune_journee_ouverte_tous_les_caissiers_servent(session: Session) -> None:
    """Sur un locataire neuf, rien n'est encore clôturé : personne n'est écarté."""
    retenus = await cashdesk._cashiers(_contexte(session))
    assert retenus == [CAISSE_A, CAISSE_B, SIGNATAIRE]


@pytest.mark.asyncio
async def test_un_caissier_dont_le_tiroir_est_arrete_est_ecarte(session: Session) -> None:
    _journee(session, CAISSE_B, CashSessionStatus.CLOSED, date.today())

    retenus = await cashdesk._cashiers(_contexte(session))

    assert CAISSE_B not in retenus
    assert retenus == [CAISSE_A, SIGNATAIRE]


@pytest.mark.asyncio
async def test_une_cloture_d_office_arrete_aussi_le_tiroir(session: Session) -> None:
    """Clôturée d'office à minuit : verrouillée aussi, personne n'a compté."""
    _journee(session, CAISSE_A, CashSessionStatus.AUTO_CLOSED, date.today())

    retenus = await cashdesk._cashiers(_contexte(session))

    assert CAISSE_A not in retenus


@pytest.mark.asyncio
async def test_une_journee_ouverte_ne_fait_ecarter_personne(session: Session) -> None:
    _journee(session, CAISSE_A, CashSessionStatus.OPEN, date.today())

    assert CAISSE_A in await cashdesk._cashiers(_contexte(session))


@pytest.mark.asyncio
async def test_une_cloture_d_hier_ne_ferme_pas_la_caisse_d_aujourd_hui(session: Session) -> None:
    """C'est la journée du jour qui décide, pas l'historique du compte."""
    _journee(session, CAISSE_A, CashSessionStatus.CLOSED, date.today() - timedelta(days=1))

    assert CAISSE_A in await cashdesk._cashiers(_contexte(session))


@pytest.mark.asyncio
async def test_toutes_les_caisses_arretees_le_dit_au_lieu_de_planter(session: Session) -> None:
    """Le message doit expliquer quoi faire, pas exposer un refus technique."""
    for cashier in (CAISSE_A, CAISSE_B, SIGNATAIRE):
        _journee(session, cashier, CashSessionStatus.CLOSED, date.today())

    with pytest.raises(BusinessValidationError) as refus:
        await cashdesk._cashiers(_contexte(session))

    assert "clôturées" in str(refus.value)


def test_une_journee_cloturee_d_office_n_est_pas_recomptee_par_le_semis() -> None:
    """`settle_cash_days` ne rouvre ni ne recompte une journée verrouillée.

    Lui inventer un montant compté et un écart effacerait la seule information
    qu'une clôture d'office porte : personne n'a ouvert le tiroir ce soir-là.
    """
    arretee = CashSession(
        cashier_user_id=CAISSE_A,
        business_date=date.today() - timedelta(days=2),
        status=CashSessionStatus.AUTO_CLOSED,
    )
    assert cashdesk._is_closed(arretee) is True
