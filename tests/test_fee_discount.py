"""Garde-fous des réductions : montants, pourcentages et payloads."""
from decimal import Decimal
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.schemas.fee_discount import DiscountInput
from app.services.fee_discount import _line


def test_percentage_cannot_exceed_one_hundred():
    with pytest.raises(ValidationError):
        DiscountInput(kind="percent", value=Decimal("100.01"), reason="Bourse approuvée")


def test_fixed_amount_requires_a_motive():
    with pytest.raises(ValidationError):
        DiscountInput(kind="fixed", value=Decimal("2500"), reason="   ")


def test_fee_line_preserves_original_amount():
    fee = SimpleNamespace(
        id=17, original_amount=Decimal("150000.00"),
        amount=Decimal("120000.00"), discount_kind="percent",
        discount_value=Decimal("20.00"), discount_reason="Remise fratrie",
    )
    line = _line(fee, "Scolarité")
    assert line.original_amount == Decimal("150000.00")
    assert line.discount_amount == Decimal("30000.00")
    assert line.payable_amount == Decimal("120000.00")


def test_non_discounted_fee_preserves_full_price():
    fee = SimpleNamespace(
        id=18, original_amount=None, amount=Decimal("10000.00"),
        discount_kind=None, discount_value=None, discount_reason=None,
    )
    line = _line(fee, "Inscription")
    assert line.discount_amount == Decimal("0")
    assert line.payable_amount == Decimal("10000.00")
