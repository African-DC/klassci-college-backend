"""Ce qu'une inscription doit encore en argent, calculé comme à la caisse.

Une seule définition, lue par l'encaissement (le reste annoncé sur l'écran de
reçu et dans la notification) et par la validation. Le même prédicat que la
cascade : un frais exonéré, déposé en nature ou soldé ne doit plus rien.
"""

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fee import cash_remaining
from app.repositories import payment_repository
from app.services import fees_paid
from app.services.payments._allocation import plannable_fees


async def remaining_cash(db: AsyncSession, enrollment_id: int) -> Decimal:
    """Le reste à payer en argent sur cette inscription, versements réels déduits."""
    frais = await payment_repository.get_enrollment_fees_ordered_by_priority(
        db, enrollment_id, lock=False
    )
    deja = await fees_paid.paid_by_enrollment(db, enrollment_id)
    avec_verse = [(fee, deja.get(fee.id, Decimal("0"))) for fee in frais]
    return sum(
        (cash_remaining(fee.status, fee.amount, paid) for fee, paid in plannable_fees(avec_verse)),
        Decimal("0"),
    )
