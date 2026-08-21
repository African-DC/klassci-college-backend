"""Bordereau journalier : à qui il est attribué, et ce qu'il ventile.

Ces tests appellent les vraies fonctions et lisent ce qu'elles produisent.
Le document consolidé du comptable et celui d'un caissier ne disent pas la
même chose : c'est cette différence qui est vérifiée ici, parce qu'elle
portait une affirmation fausse — le comptable était nommé « Le Caissier »
sur une pièce récapitulant le travail de trois autres personnes.
"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from app.models.fee import PaymentMethod, PaymentStatus
from app.services.daily_cash_book_service import cashier_breakdown
from app.services.pdf.daily_cash_book import french_long_date


@dataclass
class FakePayment:
    """Juste ce que la ventilation lit sur un versement."""

    received_by: int | None
    amount: Decimal
    method: object
    status: object


NAMES = {56: "Ibrahim Tanoh", 55: "Danielle N'Guessan"}


# ---------------------------------------------------------------------------
# Ventilation par caisse
# ---------------------------------------------------------------------------


def test_breakdown_groups_each_cashier_with_its_methods() -> None:
    """Le comptable doit lire qui a encaissé quoi, et sous quelle forme."""
    payments = [
        FakePayment(56, Decimal("25000"), "cash", "completed"),
        FakePayment(56, Decimal("15000"), "mobile_money", "completed"),
        FakePayment(55, Decimal("46000"), "cash", "completed"),
    ]

    result = cashier_breakdown(payments, NAMES)

    assert [e.cashier_name for e in result] == ["Danielle N'Guessan", "Ibrahim Tanoh"]
    danielle, ibrahim = result
    assert ibrahim.count == 2
    assert ibrahim.total == Decimal("40000")
    assert ibrahim.by_method == {"cash": Decimal("25000"), "mobile_money": Decimal("15000")}
    assert danielle.count == 1
    assert danielle.by_method == {"cash": Decimal("46000")}


def test_breakdown_ignores_cancelled_payments() -> None:
    """Un versement annulé n'a jamais alimenté le tiroir à rapprocher."""
    payments = [
        FakePayment(56, Decimal("25000"), "cash", "completed"),
        FakePayment(56, Decimal("12000"), "mobile_money", "cancelled"),
    ]

    (entry,) = cashier_breakdown(payments, NAMES)

    assert entry.count == 1
    assert entry.total == Decimal("25000")
    assert "mobile_money" not in entry.by_method


def test_breakdown_reads_enum_valued_columns() -> None:
    """SQLAlchemy rend parfois l'enum Python, parfois la chaîne : les deux comptent."""
    payments = [
        FakePayment(56, Decimal("25000"), PaymentMethod.CASH, PaymentStatus.COMPLETED),
        FakePayment(56, Decimal("12000"), PaymentMethod.CHEQUE, PaymentStatus.CANCELLED),
    ]

    (entry,) = cashier_breakdown(payments, NAMES)

    assert entry.by_method == {"cash": Decimal("25000")}
    assert entry.total == Decimal("25000")


def test_breakdown_names_an_unknown_cashier_rather_than_dropping_the_line() -> None:
    """Un versement sans caissier identifié reste dans le total du jour."""
    payments = [FakePayment(None, Decimal("5000"), "cash", "completed")]

    (entry,) = cashier_breakdown(payments, NAMES)

    assert entry.cashier_name == "—"
    assert entry.total == Decimal("5000")


def test_breakdown_of_a_day_without_payments_is_empty() -> None:
    assert cashier_breakdown([], NAMES) == []


# ---------------------------------------------------------------------------
# Date en toutes lettres
# ---------------------------------------------------------------------------


def test_long_date_is_written_in_french() -> None:
    """« Friday 21 August 2026 » en tête d'une pièce comptable française."""
    assert french_long_date(date(2026, 8, 21)) == "vendredi 21 août 2026"


def test_long_date_accepts_a_datetime() -> None:
    assert french_long_date(datetime(2026, 6, 1, 17, 30)) == "lundi 1 juin 2026"


def test_long_date_of_nothing_is_empty() -> None:
    assert french_long_date(None) == ""
