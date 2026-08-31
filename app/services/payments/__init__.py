"""Package paiements — service splitté par responsabilité.

| Sub-module | Responsabilité |
|------------|----------------|
| `_allocation` | `resolve_allocation` (porte unique, pure) + `recompute_fee_status` |
| `_response`   | builders Pydantic (Payment, PaymentAllocation) |
| `_notification` | dispatcher notif paiement (best-effort) |
| `_state`      | VALID_TRANSITIONS + logger commun |
| `recording`   | `record_enrollment_payment` (cible) + `create_payment` (legacy) |
| `preview`     | `preview_allocation` (UX caissier read-only) |
| `lifecycle`   | `validate_payment` + `cancel_payment` (transitions) |
| `query`       | `list_payments`, `get_payment`, `get_student_payments`, summary |
| `receipt`     | `get_payment_receipt_pdf` |

Les call sites historiques importent via `from app.services import payment_service`
— le module `payment_service.py` reste comme facade qui ré-exporte tout.
"""

from app.services.payments._allocation import (
    plan_allocation,
    recompute_fee_status,
    resolve_allocation,
)
from app.services.payments._notification import dispatch_payment_notification
from app.services.payments._response import allocation_to_response, payment_to_response
from app.services.payments._state import VALID_TRANSITIONS
from app.services.payments.lifecycle import cancel_payment, validate_payment
from app.services.payments.preview import preview_allocation
from app.services.payments.query import (
    get_payment,
    get_payments_summary,
    get_student_payments,
    list_payments,
)
from app.services.payments.receipt import get_payment_receipt_pdf
from app.services.payments.recording import create_payment, record_enrollment_payment

__all__ = [
    "VALID_TRANSITIONS",
    "allocation_to_response",
    "cancel_payment",
    "create_payment",
    "dispatch_payment_notification",
    "get_payment",
    "get_payment_receipt_pdf",
    "get_payments_summary",
    "get_student_payments",
    "list_payments",
    "payment_to_response",
    "plan_allocation",
    "resolve_allocation",
    "preview_allocation",
    "recompute_fee_status",
    "record_enrollment_payment",
    "validate_payment",
]
