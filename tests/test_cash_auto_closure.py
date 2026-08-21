"""Clôture d'office des journées de caisse, et régularisation a posteriori.

Ces tests appellent les vraies fonctions du service. Le dépôt est remplacé par
une implémentation en mémoire qui applique les MÊMES filtres que le SQL (statut,
date, caissier) : c'est le comportement métier qui est vérifié — ce qui est
clôturé, ce qui ne l'est pas, et ce qui reste vide — pas la forme du code.
"""

from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import pytest

from app.models.cash_session import (
    CashSession,
    CashSessionStatus,
    is_locked,
)
from app.repositories.cash_session_repository import DayAggregate, MethodTotal
from app.schemas.cash_session import CashSessionRegularizeRequest
from app.services import cash_closure_service

TODAY = date(2026, 8, 21)
YESTERDAY = date(2026, 8, 20)
TWO_DAYS_AGO = date(2026, 8, 19)


# ---------------------------------------------------------------------------
# Doublures — une session qui enregistre, un dépôt en mémoire
# ---------------------------------------------------------------------------


@dataclass
class RecordingSession:
    """Session SQLAlchemy factice : retient ce qu'on lui a demandé d'écrire."""

    added: list[Any] = field(default_factory=list)
    audit_statements: list[Any] = field(default_factory=list)
    commits: int = 0

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def execute(self, statement: Any) -> Any:
        # `audit_log` passe par `db.execute(insert(AuditLog)...)`.
        self.audit_statements.append(statement)
        return None

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1

    @asynccontextmanager
    async def begin_nested(self) -> Any:
        yield self

    @property
    def audit_entries(self) -> list[dict[str, Any]]:
        """Valeurs compilées des inserts d'audit, telles qu'écrites en base."""
        return [dict(stmt.compile().params) for stmt in self.audit_statements]


class InMemoryRepo:
    """Dépôt en mémoire appliquant les mêmes filtres que les requêtes SQL."""

    def __init__(self, sessions: list[CashSession]) -> None:
        self.sessions = sessions
        self.aggregates: dict[tuple[int, date], DayAggregate] = {}
        self.names: dict[int, str] = {}

    async def list_stale_open_sessions(
        self, _db: Any, *, before: date, limit: int
    ) -> list[CashSession]:
        stale = [
            s
            for s in self.sessions
            if s.business_date < before and s.status == CashSessionStatus.OPEN
        ]
        stale.sort(key=lambda s: (s.business_date, s.id))
        return stale[:limit]

    async def aggregate_days_by_cashier(
        self, _db: Any, pairs: list[tuple[int, date]]
    ) -> dict[tuple[int, date], DayAggregate]:
        return {key: self.aggregates[key] for key in pairs if key in self.aggregates}

    async def list_sessions_to_regularize(
        self, _db: Any, cashier_user_id: int
    ) -> list[CashSession]:
        return [
            s
            for s in self.sessions
            if s.cashier_user_id == cashier_user_id
            and s.status == CashSessionStatus.AUTO_CLOSED
            and s.regularized_at is None
        ]

    async def get_session(
        self, _db: Any, cashier_user_id: int, business_date: date
    ) -> CashSession | None:
        for s in self.sessions:
            if s.cashier_user_id == cashier_user_id and s.business_date == business_date:
                return s
        return None

    async def get_session_by_id(self, _db: Any, session_id: int) -> CashSession | None:
        return next((s for s in self.sessions if s.id == session_id), None)

    async def aggregate_day(
        self, _db: Any, cashier_user_id: int, business_date: date
    ) -> DayAggregate:
        return self.aggregates.get((cashier_user_id, business_date), DayAggregate())

    async def cashier_names(self, _db: Any, user_ids: list[int]) -> dict[int, str]:
        return {uid: self.names.get(uid, "—") for uid in user_ids}


def make_session(
    session_id: int,
    *,
    cashier: int = 7,
    business_date: date,
    status: CashSessionStatus = CashSessionStatus.OPEN,
    counted: Decimal | None = None,
    expected: Decimal | None = None,
    variance: Decimal | None = None,
) -> CashSession:
    return CashSession(
        id=session_id,
        cashier_user_id=cashier,
        business_date=business_date,
        status=status,
        opened_at=datetime(business_date.year, business_date.month, business_date.day, 8, 0),
        closed_at=None,
        counted_amount=counted,
        expected_amount=expected,
        variance=variance,
        regularized_at=None,
        notes=None,
    )


def cash_day(amount: str, count: int = 1) -> DayAggregate:
    """Une journée n'ayant encaissé que des espèces."""
    total = Decimal(amount)
    return DayAggregate(
        count=count,
        total=total,
        cash_total=total,
        by_method={"cash": MethodTotal(count=count, total=total)},
    )


@pytest.fixture
def repo(monkeypatch: pytest.MonkeyPatch):
    """Branche le dépôt en mémoire sur le service et le rend au test."""

    def _install(sessions: list[CashSession]) -> InMemoryRepo:
        fake = InMemoryRepo(sessions)
        monkeypatch.setattr(cash_closure_service, "repo", fake)
        return fake

    return _install


# ---------------------------------------------------------------------------
# Le balayage de minuit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_yesterdays_open_day_is_closed_without_a_counted_amount(repo) -> None:
    """Le cœur du métier : on ferme la journée, on n'invente pas le comptage.

    Personne n'a ouvert le tiroir. Écrire `counted_amount = 0` affirmerait
    qu'il était vide, et un écart de zéro affirmerait qu'il tombait juste.
    """
    session = make_session(1, business_date=YESTERDAY)
    fake = repo([session])
    fake.aggregates[(7, YESTERDAY)] = cash_day("120000", count=3)
    db = RecordingSession()

    report = await cash_closure_service.auto_close_stale_sessions(db, business_date=TODAY)

    assert report.closed == 1
    assert session.status == CashSessionStatus.AUTO_CLOSED
    assert session.closed_at is not None
    # Le théorique est figé, comme sur une clôture normale.
    assert session.expected_amount == Decimal("120000")
    # Et surtout : rien d'inventé.
    assert session.counted_amount is None, "personne n'a compté ce tiroir"
    assert session.variance is None, "l'écart est INCONNU, pas nul"
    assert session.regularized_at is None


@pytest.mark.asyncio
async def test_todays_open_day_is_left_alone(repo) -> None:
    """La caisse du jour est en plein service : y toucher couperait le guichet."""
    today_session = make_session(1, business_date=TODAY)
    fake = repo([today_session])
    fake.aggregates[(7, TODAY)] = cash_day("50000")
    db = RecordingSession()

    report = await cash_closure_service.auto_close_stale_sessions(db, business_date=TODAY)

    assert report.closed == 0
    assert today_session.status == CashSessionStatus.OPEN
    assert today_session.expected_amount is None
    assert db.commits == 0, "rien à faire ne doit pas ouvrir de transaction"


@pytest.mark.asyncio
async def test_replaying_the_sweep_changes_nothing(repo) -> None:
    """Idempotence : la tâche peut être rejouée sans reclôturer ni fausser."""
    session = make_session(1, business_date=YESTERDAY)
    fake = repo([session])
    fake.aggregates[(7, YESTERDAY)] = cash_day("90000")
    db = RecordingSession()

    first = await cash_closure_service.auto_close_stale_sessions(db, business_date=TODAY)
    closed_at = session.closed_at
    expected = session.expected_amount

    second = await cash_closure_service.auto_close_stale_sessions(db, business_date=TODAY)

    assert first.closed == 1
    assert second.closed == 0
    assert session.closed_at == closed_at
    assert session.expected_amount == expected
    assert len(db.added) == 1, "pas de seconde notification au caissier"


@pytest.mark.asyncio
async def test_a_day_closed_by_its_cashier_is_never_touched(repo) -> None:
    """Un écart constaté et signé ne doit pas bouger sous les pieds du comptable."""
    signed = make_session(
        1,
        business_date=YESTERDAY,
        status=CashSessionStatus.CLOSED,
        counted=Decimal("119000"),
        expected=Decimal("120000"),
        variance=Decimal("-1000"),
    )
    fake = repo([signed])
    fake.aggregates[(7, YESTERDAY)] = cash_day("120000")
    db = RecordingSession()

    report = await cash_closure_service.auto_close_stale_sessions(db, business_date=TODAY)

    assert report.closed == 0
    assert signed.status == CashSessionStatus.CLOSED
    assert signed.counted_amount == Decimal("119000")
    assert signed.variance == Decimal("-1000")


@pytest.mark.asyncio
async def test_a_day_without_any_cash_freezes_zero_not_none(repo) -> None:
    """Sans agrégat, le théorique vaut zéro — c'est un fait, pas une inconnue.

    L'inconnue, c'est le comptage : lui reste nul.
    """
    session = make_session(1, business_date=YESTERDAY)
    repo([session])  # aucun agrégat enregistré pour cette journée
    db = RecordingSession()

    await cash_closure_service.auto_close_stale_sessions(db, business_date=TODAY)

    assert session.expected_amount == Decimal("0")
    assert session.counted_amount is None
    assert session.variance is None


@pytest.mark.asyncio
async def test_the_batch_is_bounded_and_says_so(repo) -> None:
    """La 0044 a laissé des centaines de journées ouvertes : on traite par lots.

    Un rattrapage partiel doit se déclarer partiel, sinon il passe pour complet.
    """
    sessions = [make_session(i, business_date=date(2026, 8, i)) for i in range(1, 6)]
    repo(sessions)
    db = RecordingSession()

    report = await cash_closure_service.auto_close_stale_sessions(db, business_date=TODAY, limit=2)

    assert report.closed == 2
    assert report.has_more is True
    # Les plus vieilles d'abord : la comptabilité rattrape dans l'ordre.
    assert [s.status for s in sessions] == [
        CashSessionStatus.AUTO_CLOSED,
        CashSessionStatus.AUTO_CLOSED,
        CashSessionStatus.OPEN,
        CashSessionStatus.OPEN,
        CashSessionStatus.OPEN,
    ]


# ---------------------------------------------------------------------------
# Trace et notification — une clôture d'office engage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_audit_trail_names_the_cashier_who_should_have_counted(repo) -> None:
    session = make_session(1, cashier=42, business_date=YESTERDAY)
    fake = repo([session])
    fake.aggregates[(42, YESTERDAY)] = cash_day("75000")
    db = RecordingSession()

    await cash_closure_service.auto_close_stale_sessions(db, business_date=TODAY)

    entries = db.audit_entries
    assert len(entries) == 1
    entry = entries[0]
    assert entry["entity_type"] == "cash_session"
    assert entry["entity_id"] == 1
    # Le système agit, pas le caissier : lui attribuer l'acte serait un faux.
    assert entry["user_id"] is None
    new_values = entry["new_values"]
    assert new_values["status"] == CashSessionStatus.AUTO_CLOSED.value
    assert new_values["cashier_user_id"] == 42
    assert new_values["expected_amount"] == 75000.0
    assert new_values["counted_amount"] is None
    assert new_values["variance"] is None
    assert "office" in (entry["notes"] or "")


@pytest.mark.asyncio
async def test_each_cashier_gets_one_notification_listing_their_days(repo) -> None:
    """Une notification par caissier et par exécution, pas une par journée."""
    sessions = [
        make_session(1, cashier=7, business_date=TWO_DAYS_AGO),
        make_session(2, cashier=7, business_date=YESTERDAY),
        make_session(3, cashier=9, business_date=YESTERDAY),
    ]
    repo(sessions)
    db = RecordingSession()

    report = await cash_closure_service.auto_close_stale_sessions(db, business_date=TODAY)

    assert report.closed == 3
    assert report.cashiers_notified == 2
    assert len(db.added) == 2
    by_user = {n.user_id: n for n in db.added}
    assert set(by_user) == {7, 9}
    assert "19/08/2026" in by_user[7].body
    assert "20/08/2026" in by_user[7].body
    assert "régulariser" in by_user[7].body.lower()
    assert by_user[9].read is False


def test_a_long_list_of_days_is_summarised_not_enumerated() -> None:
    """Quarante dates dans une notification n'aident personne à agir."""
    days = [date(2026, 7, day) for day in range(1, 13)]
    body = cash_closure_service._notification_body(days)

    assert "01/07/2026" in body
    assert "et 7 autres" in body
    assert "12/07/2026" not in body


def test_one_day_is_announced_in_the_singular() -> None:
    body = cash_closure_service._notification_body([YESTERDAY])

    assert body.startswith("Votre journée de caisse du 20/08/2026 a été clôturée d'office")


def test_several_days_are_announced_in_the_plural() -> None:
    """« Votre journées de caisse du A, B ont été clôturées » était fautif."""
    body = cash_closure_service._notification_body([TWO_DAYS_AGO, YESTERDAY])

    assert body.startswith(
        "Vos journées de caisse des 19/08/2026 et 20/08/2026 ont été clôturées d'office"
    )
    assert "Votre journées" not in body


# ---------------------------------------------------------------------------
# Régularisation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_regularizing_produces_the_real_variance_and_leaves_a_trace(repo) -> None:
    """L'écart naît au comptage, contre le théorique figé la nuit de la clôture."""
    session = make_session(
        1,
        business_date=YESTERDAY,
        status=CashSessionStatus.AUTO_CLOSED,
        expected=Decimal("120000"),
    )
    fake = repo([session])
    fake.names[7] = "Sophie Yao"
    db = RecordingSession()

    response = await cash_closure_service.regularize_my_session(
        db,
        7,
        YESTERDAY,
        CashSessionRegularizeRequest(counted_amount=118500, notes="  Oubli de clôture  "),
    )

    assert session.status == CashSessionStatus.CLOSED
    assert session.counted_amount == Decimal("118500")
    assert session.variance == Decimal("-1500"), "manquant de 1 500 FCFA"
    assert session.regularized_at is not None
    assert session.notes == "Oubli de clôture", "les espaces parasites sont retirés"
    assert response.variance == -1500.0
    assert response.cashier_name == "Sophie Yao"

    entry = db.audit_entries[-1]
    assert entry["user_id"] == 7, "cette fois c'est bien le caissier qui agit"
    assert entry["new_values"]["variance"] == -1500.0
    assert entry["new_values"]["status"] == CashSessionStatus.CLOSED.value
    assert entry["old_values"]["status"] == CashSessionStatus.AUTO_CLOSED.value


@pytest.mark.asyncio
async def test_regularizing_uses_the_frozen_expected_not_a_fresh_one(repo) -> None:
    """Recalculer le théorique ferait bouger une base déjà arrêtée."""
    session = make_session(
        1,
        business_date=YESTERDAY,
        status=CashSessionStatus.AUTO_CLOSED,
        expected=Decimal("120000"),
    )
    fake = repo([session])
    # Un versement a été rattrapé depuis : l'agrégat vivant a changé.
    fake.aggregates[(7, YESTERDAY)] = cash_day("200000")
    db = RecordingSession()

    await cash_closure_service.regularize_my_session(
        db, 7, YESTERDAY, CashSessionRegularizeRequest(counted_amount=120000)
    )

    assert session.variance == Decimal("0"), "l'écart se mesure contre le figé"


@pytest.mark.asyncio
async def test_a_normally_closed_day_cannot_be_regularized(repo) -> None:
    """Rouvrir un comptage signé effacerait un écart déjà remis à la direction."""
    from fastapi import HTTPException

    session = make_session(
        1,
        business_date=YESTERDAY,
        status=CashSessionStatus.CLOSED,
        counted=Decimal("119000"),
        expected=Decimal("120000"),
        variance=Decimal("-1000"),
    )
    repo([session])
    db = RecordingSession()

    with pytest.raises(HTTPException) as excinfo:
        await cash_closure_service.regularize_my_session(
            db, 7, YESTERDAY, CashSessionRegularizeRequest(counted_amount=120000)
        )

    assert excinfo.value.status_code == 409
    assert session.counted_amount == Decimal("119000")
    assert session.variance == Decimal("-1000")


@pytest.mark.asyncio
async def test_a_regularized_day_leaves_the_to_do_list(repo) -> None:
    """Ce que le caissier voit à sa connexion, avant et après régularisation."""
    session = make_session(
        1,
        business_date=YESTERDAY,
        status=CashSessionStatus.AUTO_CLOSED,
        expected=Decimal("60000"),
    )
    fake = repo([session])
    fake.names[7] = "Sophie Yao"
    db = RecordingSession()

    pending = await cash_closure_service.list_sessions_to_regularize(db, 7)
    assert [p.business_date for p in pending] == [YESTERDAY]
    assert pending[0].counted_amount is None
    assert pending[0].variance is None

    await cash_closure_service.regularize_my_session(
        db, 7, YESTERDAY, CashSessionRegularizeRequest(counted_amount=60000)
    )

    assert await cash_closure_service.list_sessions_to_regularize(db, 7) == []


@pytest.mark.asyncio
async def test_another_cashiers_day_is_not_mine_to_regularize(repo) -> None:
    """Cloisonnement : chacun ne régularise que sa propre caisse."""
    session = make_session(
        1,
        cashier=9,
        business_date=YESTERDAY,
        status=CashSessionStatus.AUTO_CLOSED,
        expected=Decimal("60000"),
    )
    repo([session])
    db = RecordingSession()

    assert await cash_closure_service.list_sessions_to_regularize(db, 7) == []


# ---------------------------------------------------------------------------
# Verrouillage — une journée clôturée d'office est verrouillée aussi
# ---------------------------------------------------------------------------


def test_an_auto_closed_day_is_locked_like_a_signed_one() -> None:
    """Son théorique est figé : y encaisser ou y annuler le rendrait faux."""
    assert is_locked(CashSessionStatus.AUTO_CLOSED) is True
    assert is_locked(CashSessionStatus.CLOSED) is True
    assert is_locked(CashSessionStatus.OPEN) is False
    # SQLAlchemy rend tantôt l'énum, tantôt la chaîne selon le chemin de lecture.
    assert is_locked("auto_closed") is True
    assert is_locked("open") is False
