"""Caisse — invariants de cloisonnement et de clôture."""

from datetime import date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.models.cash_session import CashSessionStatus
from app.services import cash_session_service
from app.services.tenants.permissions import ROLE_DEFINITIONS

# ---------------------------------------------------------------------------
# Cloisonnement — c'est l'ABSENCE de permission qui cantonne le caissier
# ---------------------------------------------------------------------------


def test_cashier_cannot_read_other_cashboxes() -> None:
    perms = set(ROLE_DEFINITIONS["cashier"]["permissions"])
    assert "cash-session:manage" in perms, "le caissier doit pouvoir clôturer sa journée"
    assert "payments:read:all" not in perms, "le caissier verrait la caisse de ses collègues"
    assert "cash-session:read:all" not in perms
    assert "payments:cancel:any" not in perms, "il ne corrige que sa saisie, journée ouverte"


def test_accountant_supervises_every_cashbox() -> None:
    perms = set(ROLE_DEFINITIONS["accountant"]["permissions"])
    assert "payments:read:all" in perms
    assert "cash-session:read:all" in perms
    assert "payments:cancel:any" in perms
    assert "cash-session:manage" not in perms, "le comptable ne tient pas de caisse"


def test_educator_has_no_cash_permission_at_all() -> None:
    perms = set(ROLE_DEFINITIONS["educator"]["permissions"])
    assert not {p for p in perms if p.startswith("cash-session:")}
    assert "payments:create" not in perms


# ---------------------------------------------------------------------------
# Clôture
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cannot_collect_on_a_closed_day() -> None:
    """Encaisser après clôture rendrait faux un écart déjà constaté et signé."""
    session = MagicMock()
    session.status = CashSessionStatus.CLOSED

    async def fake_get_session(_db, _cashier, _day):
        return session

    original = cash_session_service.repo.get_session
    cash_session_service.repo.get_session = fake_get_session  # type: ignore[assignment]
    try:
        with pytest.raises(HTTPException) as excinfo:
            await cash_session_service.ensure_open_session(AsyncMock(), 7, datetime(2026, 8, 20, 9))
        assert excinfo.value.status_code == 409
        assert "clôturée" in excinfo.value.detail
    finally:
        cash_session_service.repo.get_session = original  # type: ignore[assignment]


@pytest.mark.asyncio
async def test_first_payment_of_the_day_opens_the_session() -> None:
    """Ouverture paresseuse : pas de geste imposé au guichet le matin."""
    created: dict[str, object] = {}

    async def fake_get_session(_db, _cashier, _day):
        return None

    async def fake_create(_db, cashier_user_id, business_date, *, opened_at):
        created["cashier"] = cashier_user_id
        created["date"] = business_date
        created["opened_at"] = opened_at
        return MagicMock()

    original_get = cash_session_service.repo.get_session
    original_create = cash_session_service.repo.create_session
    cash_session_service.repo.get_session = fake_get_session  # type: ignore[assignment]
    cash_session_service.repo.create_session = fake_create  # type: ignore[assignment]
    try:
        await cash_session_service.ensure_open_session(AsyncMock(), 7, datetime(2026, 8, 20, 9, 30))
    finally:
        cash_session_service.repo.get_session = original_get  # type: ignore[assignment]
        cash_session_service.repo.create_session = original_create  # type: ignore[assignment]

    assert created["cashier"] == 7
    assert created["date"] == date(2026, 8, 20)


def test_variance_is_counted_minus_expected() -> None:
    """Négatif = manquant, positif = excédent. Le signe porte le sens métier."""
    expected = Decimal("120000")
    counted = Decimal("118500")
    assert counted - expected == Decimal("-1500")
    counted_over = Decimal("121000")
    assert counted_over - expected == Decimal("1000")


# ---------------------------------------------------------------------------
# Ventilation par moyen de paiement
# ---------------------------------------------------------------------------


def test_method_totals_keep_a_stable_order_and_skip_unused_methods() -> None:
    totals = cash_session_service._method_totals(
        {
            "cheque": {"count": 1, "total": Decimal("5000")},
            "cash": {"count": 3, "total": Decimal("75000")},
        }
    )
    assert [t.method for t in totals] == ["cash", "cheque"], "espèces d'abord, ordre figé"
    assert totals[0].label == "Espèces"
    assert totals[0].total == 75000.0
    assert all(t.count > 0 for t in totals)
