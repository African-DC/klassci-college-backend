"""Le tiroir ne concerne que les espèces, et aucun total ne perd une ligne.

Deux règles qui n'étaient jusqu'ici que supposées.

**Le tiroir.** Une journée de caisse existe parce qu'un billet se compte le
soir et qu'un écart se constate. Un virement ou un versement Wave laisse une
trace bancaire ou opérateur : il n'y a rien à compter. Le flux d'encaissement
ouvrait pourtant une journée de caisse pour tout versement, y compris un
virement encaissé par un comptable qui n'a pas `cash-session:manage` et ne
pourra donc jamais la clôturer — pendant que le flux legacy n'en ouvrait
aucune et laissait passer des espèces sur une journée déjà close.

**La ventilation.** Le récapitulatif par moyen se construisait en parcourant
une constante et en y piochant les montants. Tout moyen absent de cette
constante disparaissait du récapitulatif tout en restant compté dans le total :
le document se contredisait sans le dire.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.dependencies import TokenData
from app.models.cash_session import CashSessionStatus
from app.repositories.cash_session_repository import DayAggregate, MethodTotal
from app.services import cash_session_service
from app.services.payments import recording
from app.services.pdf.daily_cash_book import _totals_rows

ACTOR = TokenData(user_id=7, tenant_id="local", email="comptable@college.ci")


# ---------------------------------------------------------------------------
# Le tiroir
# ---------------------------------------------------------------------------


@pytest.fixture
def drawer_calls(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Enregistre les ouvertures de journée de caisse déclenchées."""
    calls: list[int] = []

    async def _fake_ensure_open_session(_db: object, cashier_id: int, _when: datetime) -> None:
        calls.append(cashier_id)

    async def _allow_everything(_db: object, _actor: object, _method: str) -> None:
        return None

    monkeypatch.setattr(
        recording.cash_session_service, "ensure_open_session", _fake_ensure_open_session
    )
    monkeypatch.setattr(recording.payment_methods, "ensure_method_allowed", _allow_everything)
    return calls


@pytest.mark.asyncio
async def test_un_versement_en_especes_exige_une_journee_de_caisse(
    drawer_calls: list[int],
) -> None:
    await recording._guard_method_and_drawer(
        AsyncMock(), ACTOR, "cash", when=datetime(2026, 8, 21, 9)
    )
    assert drawer_calls == [7], "les espèces engagent un tiroir, donc une journée ouverte"


@pytest.mark.asyncio
async def test_aucun_autre_moyen_nouvre_de_journee_de_caisse(
    drawer_calls: list[int],
) -> None:
    for method in ("wave", "mtn_momo", "orange_money", "moov_money", "bank_transfer", "cheque"):
        await recording._guard_method_and_drawer(
            AsyncMock(), ACTOR, method, when=datetime(2026, 8, 21, 9)
        )
    assert drawer_calls == [], "un virement ou un Wave ne laisse rien à compter le soir"


@pytest.mark.asyncio
async def test_une_journee_close_refuse_encore_les_especes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Le verrou de clôture porte bien sur le chemin espèces, pas ailleurs."""
    from fastapi import HTTPException

    session = MagicMock()
    session.status = CashSessionStatus.CLOSED

    async def _fake_get_session(_db: object, _cashier: int, _day: date) -> object:
        return session

    async def _allow_everything(_db: object, _actor: object, _method: str) -> None:
        return None

    monkeypatch.setattr(cash_session_service.repo, "get_session", _fake_get_session)
    monkeypatch.setattr(recording.payment_methods, "ensure_method_allowed", _allow_everything)

    with pytest.raises(HTTPException) as excinfo:
        await recording._guard_method_and_drawer(
            AsyncMock(), ACTOR, "cash", when=datetime(2026, 8, 21, 9)
        )
    assert excinfo.value.status_code == 409

    # Le même jour clos ne bloque pas un virement : il n'y a pas de tiroir.
    await recording._guard_method_and_drawer(
        AsyncMock(), ACTOR, "bank_transfer", when=datetime(2026, 8, 21, 9)
    )


# ---------------------------------------------------------------------------
# La ventilation
# ---------------------------------------------------------------------------


def _aggregate(**by_method: str) -> DayAggregate:
    rows = {k: MethodTotal(count=1, total=Decimal(v)) for k, v in by_method.items()}
    return DayAggregate(
        count=len(rows),
        total=sum((m.total for m in rows.values()), Decimal("0")),
        cash_total=rows["cash"].total if "cash" in rows else Decimal("0"),
        by_method=rows,
    )


def _response(aggregate: DayAggregate) -> Any:
    session = MagicMock()
    session.id = 1
    session.cashier_user_id = 7
    session.business_date = date(2026, 8, 21)
    session.status = CashSessionStatus.OPEN
    session.opened_at = datetime(2026, 8, 21, 8)
    session.closed_at = None
    session.counted_amount = None
    session.expected_amount = None
    session.variance = None
    session.regularized_at = None
    session.notes = None
    return cash_session_service.to_response(session, cashier_name="Sophie", aggregate=aggregate)


def test_la_ventilation_de_caisse_couvre_les_quatre_operateurs() -> None:
    result = _response(_aggregate(cash="1000", wave="2000", mtn_momo="3000", moov_money="4000"))
    assert [line.method for line in result.by_method] == [
        "cash",
        "wave",
        "mtn_momo",
        "moov_money",
    ], "l'ordre suit la fréquence au guichet, pas l'alphabet"
    assert [line.label for line in result.by_method] == [
        "Espèces",
        "Wave",
        "MTN MoMo",
        "Moov Money",
    ]


def test_la_ventilation_de_caisse_ne_perd_jamais_un_moyen() -> None:
    """La somme des lignes doit égaler le total, moyen inconnu compris."""
    aggregate = _aggregate(cash="1000", mobile_money="500", un_moyen_inattendu="250")
    result = _response(aggregate)

    assert sum(line.total for line in result.by_method) == pytest.approx(result.total_collected)
    assert "un_moyen_inattendu" in [line.method for line in result.by_method]
    # Le libellé retombe sur la clé brute : une valeur inconnue doit se voir,
    # pas se fondre dans un « Autre » qui ferait mentir la ligne.
    assert result.by_method[-1].label == "un_moyen_inattendu"


def test_le_versement_historique_garde_son_libelle_dorigine() -> None:
    """Un reçu réimprimé doit dire ce que la famille a sur son papier."""
    result = _response(_aggregate(mobile_money="500"))
    assert result.by_method[0].label == "Mobile Money"


def test_le_bordereau_ne_perd_jamais_un_moyen() -> None:
    totals = {
        "cheque": Decimal("100"),
        "cash": Decimal("200"),
        "moov_money": Decimal("300"),
        "mobile_money": Decimal("50"),
        "un_moyen_inattendu": Decimal("25"),
    }
    rows = _totals_rows(totals)

    assert [row[0] for row in rows] == [
        "Espèces",
        "Moov Money",
        "Chèque",
        "Mobile Money",
        "un_moyen_inattendu",
    ]
    assert len(rows) == len(totals), "aucune ligne ne doit disparaître du récapitulatif"


def test_le_bordereau_dune_journee_sans_versement_na_pas_de_ligne() -> None:
    assert _totals_rows({}) == []
