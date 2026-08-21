"""Transitions de statut d'un versement : ce qui passe, et ce qu'on lit quand ça bloque.

Le message de refus part au guichet et se retrouve dans le journal d'audit
financier. Il doit nommer l'état du versement, pas le symbole Python qui le
représente en mémoire.
"""

import pytest
from fastapi import HTTPException

from app.models.fee import PaymentStatus
from app.services.payments._state import status_value
from app.services.payments.lifecycle import _ensure_transition_allowed


def test_status_value_reads_an_enum() -> None:
    assert status_value(PaymentStatus.COMPLETED) == "completed"


def test_status_value_leaves_a_plain_string_alone() -> None:
    assert status_value("completed") == "completed"


def test_a_completed_payment_may_still_be_cancelled() -> None:
    """Correction comptable : annuler un versement validé reste possible."""
    _ensure_transition_allowed(PaymentStatus.COMPLETED, "cancelled")
    _ensure_transition_allowed("completed", "cancelled")


def test_a_pending_payment_may_be_validated() -> None:
    _ensure_transition_allowed(PaymentStatus.PENDING, "completed")


@pytest.mark.parametrize("current", [PaymentStatus.COMPLETED, "completed"])
def test_refusal_names_the_status_not_the_python_symbol(current: object) -> None:
    """« impossible de passer de 'PaymentStatus.COMPLETED' » n'a rien à faire au guichet."""
    with pytest.raises(HTTPException) as exc:
        _ensure_transition_allowed(current, "completed")

    assert exc.value.status_code == 409
    assert "'completed'" in exc.value.detail
    assert "PaymentStatus" not in exc.value.detail


def test_a_cancelled_payment_is_a_dead_end() -> None:
    for target in ("completed", "cancelled", "refunded"):
        with pytest.raises(HTTPException) as exc:
            _ensure_transition_allowed(PaymentStatus.CANCELLED, target)
        assert exc.value.status_code == 409
