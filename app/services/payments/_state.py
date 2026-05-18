"""État interne du domaine paiement : transitions valides + logger commun."""

import logging

logger = logging.getLogger(__name__)


# State machine des transitions de statut Payment
VALID_TRANSITIONS: dict[str, list[str]] = {
    "pending": ["completed", "cancelled"],
    "completed": ["refunded", "cancelled"],  # cancel d'un completed = correction comptable
    "failed": [],
    "refunded": [],
    "cancelled": [],
}
