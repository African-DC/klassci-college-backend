"""Qui a le droit de lire ce qu'une famille doit.

Dans un établissement, le montant dû par une famille est une information
sensible : elle dit la situation économique du foyer. Le professeur principal
n'en a pas besoin pour faire cours, et le directeur des études qui préside un
conseil de classe ne devrait pas savoir qu'une famille est en retard pendant
qu'on décide du passage de l'enfant.

Deux niveaux, donc, et un seul endroit pour en décider :

- `payments:read` — les montants. Réservé à qui manipule l'argent.
- `payments:status:read` — « à jour » ou « en retard », et la date du dernier
  versement. De quoi valider un dossier d'inscription sans jamais apprendre
  combien la famille doit.

Le second est délibérément pauvre : une date et un état ne permettent pas de
reconstituer une somme.
"""

from dataclasses import dataclass
from datetime import date
from typing import ClassVar

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

# Tout champ portant un montant. Redigés d'un bloc plutôt qu'un par un : un
# champ financier ajouté plus tard sans être listé ici fuiterait en silence.
AMOUNT_FIELDS = frozenset(
    {
        "fees_expected",
        "fees_paid",
        "fees_remaining",
        "fees_rate",
        "fees_balance",
        # Ce que la famille doit sur les AUTRES exercices — même sensibilité
        # que le solde de l'année, et même masquage.
        "fees_arrears_other_years",
    }
)

STATUS_UP_TO_DATE = "a_jour"
STATUS_LATE = "en_retard"
STATUS_NO_SCHEDULE = "sans_echeancier"


@dataclass(frozen=True, slots=True)
class FinanceView:
    """Ce que l'appelant a le droit de voir des finances d'un élève.

    Se passe toujours explicitement. Le paramètre a longtemps été optionnel,
    et son absence ouvrait tout : un appelant qui oubliait l'argument publiait
    les montants sans que rien, ni le type ni un test, ne le signale. Un garde
    dont l'oubli est permissif n'est pas un garde.
    """

    amounts: bool
    status: bool

    #: Ce que voit le logiciel lui-même — PDF, exports, courriels — quand il
    #: compose un document dont l'accès a déjà été autorisé en amont. À écrire
    #: en toutes lettres à l'appel : la lecture doit être un choix visible.
    INTERNAL: ClassVar["FinanceView"]

    @classmethod
    def of(cls, *, may_read_payments: bool, may_read_status: bool) -> "FinanceView":
        # Voir les montants implique voir l'état : refuser le badge à un
        # comptable parce qu'on ne lui a pas coché la permission la plus
        # faible serait absurde.
        return cls(amounts=may_read_payments, status=may_read_payments or may_read_status)


FinanceView.INTERNAL = FinanceView(amounts=True, status=True)


def redact(block: dict, view: FinanceView) -> dict:
    """Met à `None` les montants que l'appelant n'a pas le droit de lire.

    On renvoie `None`, pas `0`. Un zéro se lit « la famille ne doit rien »,
    ce qui est un mensonge ; `None` se lit « vous ne voyez pas cette
    information », et l'écran peut afficher un tiret honnête.
    """
    if view.amounts:
        return block
    return {key: (None if key in AMOUNT_FIELDS else value) for key, value in block.items()}


async def payment_pulse(
    db: AsyncSession, enrollment_id: int | None, *, today: date | None = None
) -> tuple[str | None, date | None]:
    """État de paiement et date du dernier versement, sans aucun montant.

    L'état vient de l'échéancier, comme partout ailleurs depuis le lot des
    tranches : une famille qui respecte son calendrier est « à jour » même si
    le solde de l'année reste ouvert.
    """
    if enrollment_id is None:
        return None, None

    from app.models.fee import Payment, PaymentStatus
    from app.services.installments import resolve_schedule

    schedule = await resolve_schedule(db, enrollment_id, today=today)
    if not schedule.lines:
        status = STATUS_NO_SCHEDULE
    else:
        status = STATUS_LATE if schedule.is_late else STATUS_UP_TO_DATE

    last_payment = (
        await db.execute(
            select(func.max(Payment.created_at)).where(
                Payment.enrollment_id == enrollment_id,
                Payment.status == PaymentStatus.COMPLETED,
            )
        )
    ).scalar()

    return status, last_payment.date() if last_payment else None
