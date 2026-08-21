"""État interne du domaine paiement : transitions valides + logger commun."""

import enum
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


def status_value(status: object) -> object:
    """Valeur lisible d'un statut, qu'il arrive en enum ou en chaîne.

    SQLAlchemy rend tantôt `PaymentStatus.COMPLETED`, tantôt `"completed"`,
    selon que l'objet sort du cache d'identité de la session ou d'une lecture
    fraîche. Les deux formes se comparent et se hachent de la même façon — les
    tables de transition marchaient donc dans les deux cas. C'est l'affichage
    qui trahissait la différence : interpolé tel quel, le premier cas mettait
    « PaymentStatus.COMPLETED », le nom d'un symbole Python, sur un message
    lu au guichet et dans le journal d'audit financier.
    """
    return status.value if isinstance(status, enum.Enum) else status
