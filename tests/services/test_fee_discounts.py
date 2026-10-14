"""Règles monétaires des réductions : calcul décimal, limites, annulation."""

from decimal import Decimal

import pytest

from app.core.exceptions import BusinessValidationError
from app.schemas.fee_discount import FeeDiscountUpsert
from app.services.fee_discounts import compute_discount


@pytest.mark.parametrize(
    ("base", "kind", "value", "expected"),
    [
        ("150000", "fixed", "25000", "25000.00"),
        ("150000", "percent", "20", "30000.00"),
        ("100001", "percent", "33.33", "33330.33"),
        ("150000", "percent", "100", "150000.00"),
    ],
)
def test_amounts_are_exact(base: str, kind: str, value: str, expected: str) -> None:
    payload = FeeDiscountUpsert(kind=kind, value=Decimal(value), reason="Aide sociale")
    assert compute_discount(Decimal(base), payload) == Decimal(expected)


def test_cannot_discount_more_than_fee() -> None:
    with pytest.raises(BusinessValidationError):
        compute_discount(
            Decimal("25000"),
            FeeDiscountUpsert(kind="fixed", value=Decimal("25001"), reason="Aide sociale"),
        )


def test_percentage_cannot_exceed_100() -> None:
    with pytest.raises(BusinessValidationError):
        compute_discount(
            Decimal("25000"),
            FeeDiscountUpsert(kind="percent", value=Decimal("101"), reason="Aide sociale"),
        )


def test_blank_reason_is_rejected() -> None:
    with pytest.raises(ValueError):
        FeeDiscountUpsert(kind="fixed", value=Decimal("2000"), reason="    ")
