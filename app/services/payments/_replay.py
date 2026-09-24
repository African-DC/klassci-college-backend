"""Un renvoi de l'écran ne doit pas encaisser deux fois.

Au guichet, sur une 3G qui coupe, la caissière appuie sur « Enregistrer »,
l'écran tourne, elle appuie encore. L'écran tire une clé par envoi et la
renvoie identique à chaque tentative ; ce module retrouve le versement déjà
écrit sous cette clé (migration 0083).
"""

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessValidationError
from app.repositories import payment_repository as repo
from app.schemas.payment import EnrollmentPaymentCreate, PaymentResponse
from app.services.payments._response import payment_to_response
from app.services.payments._state import logger
from app.services.payments.remaining import remaining_cash


async def versement_deja_ecrit(
    db: AsyncSession, enrollment_id: int, data: EnrollmentPaymentCreate
) -> PaymentResponse | None:
    """Le versement déjà écrit sous cette clé d'envoi, s'il existe.

    C'est un renvoi de l'écran après une coupure : on rend ce qui a été écrit,
    sans rien réécrire ni renotifier. Une clé qui désigne un autre versement
    (autre inscription, autre montant) n'est pas un renvoi mais une erreur de
    l'écran : on la refuse plutôt que de rendre un reçu qui ne correspond pas.
    """
    if not data.idempotency_key:
        return None
    payment_id = await repo.get_payment_id_by_idempotency_key(db, data.idempotency_key)
    if payment_id is None:
        return None
    deja = await repo.get_payment_with_allocations(db, payment_id)
    if deja is None:
        return None
    if deja.enrollment_id != enrollment_id or deja.amount != data.amount:
        raise BusinessValidationError(
            "Cet envoi a déjà servi pour un autre versement. Rechargez la page avant de réessayer."
        )
    logger.info("Versement %d rendu tel quel : renvoi de la meme cle d'envoi", payment_id)
    return avec_reste(payment_to_response(deja), await remaining_cash(db, enrollment_id))


def avec_reste(response: PaymentResponse, reste: Decimal) -> PaymentResponse:
    """La réponse d'encaissement, avec le reste à payer lu en base à l'instant."""
    return response.model_copy(update={"enrollment_remaining_after": float(reste)})
