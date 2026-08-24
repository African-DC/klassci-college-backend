"""Le bandeau et la liste doivent parler du même périmètre.

Le récapitulatif ne recevait que l'année scolaire. Filtrer la liste sur
« Annulé » laissait donc le bandeau annoncer tout l'argent reçu au-dessus d'un
tableau qui en montrait trois. Deux chiffres, deux périmètres, et rien à
l'écran pour dire lequel on lit.

La moitié caisse suit désormais les filtres. Le recouvrement ne les suit pas,
et c'est délibéré : il parle de la dette de l'école, pas des lignes affichées.
Filtrer une dette sur un moyen de paiement ne veut rien dire.

Les tests exécutent la vraie agrégation sur SQLite, avec le vrai prédicat de
la liste. Inspecter la signature aurait figé une forme sans rien prouver du
résultat.
"""

from collections.abc import Iterator
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models.fee import Payment
from app.repositories.payment_filters import PaymentFilters
from app.services.payments import query

CAISSIERE = 7


class _AsyncBridge:
    def __init__(self, session: Session) -> None:
        self._session = session

    async def execute(self, statement: object) -> object:
        return self._session.execute(statement)  # type: ignore[arg-type]


def _versement(pid: int, montant: str, statut: str, methode: str = "cash") -> Payment:
    return Payment(
        id=pid,
        enrollment_id=None,
        amount=Decimal(montant),
        method=methode,
        status=statut,
        received_by=CAISSIERE,
    )


@pytest.fixture()
def db() -> Iterator[Session]:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[Payment.__table__])
    with Session(engine) as session:
        session.add_all(
            [
                _versement(1, "10000", "completed"),
                _versement(2, "3000", "cancelled"),
                _versement(3, "5000", "cancelled", methode="mobile_money"),
                _versement(4, "2000", "pending"),
            ]
        )
        session.flush()
        yield session


async def _recap(session: Session, filtres: PaymentFilters | None):
    return await query.get_payments_summary(
        _AsyncBridge(session), received_by=CAISSIERE, filters=filtres
    )


@pytest.mark.asyncio
async def test_sans_filtre_le_bandeau_compte_tout(db: Session) -> None:
    recap = await _recap(db, None)
    assert recap.payment_count == 4


@pytest.mark.asyncio
async def test_filtrer_sur_annule_ne_compte_que_les_annules(db: Session) -> None:
    # Le défaut, tenu par ce test : avant, le bandeau annonçait 4 au-dessus
    # d'une liste qui en montrait 2.
    recap = await _recap(db, PaymentFilters(status="cancelled"))
    assert recap.payment_count == 2
    assert recap.total_cancelled == 8000.0


@pytest.mark.asyncio
async def test_le_moyen_de_paiement_restreint_aussi(db: Session) -> None:
    recap = await _recap(db, PaymentFilters(method="mobile_money"))
    assert recap.payment_count == 1


@pytest.mark.asyncio
async def test_deux_filtres_se_cumulent(db: Session) -> None:
    recap = await _recap(db, PaymentFilters(status="cancelled", method="cash"))
    assert recap.payment_count == 1
    assert recap.total_cancelled == 3000.0
