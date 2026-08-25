"""Session de caisse — une journée de guichet pour un caissier.

Le rattachement d'un versement à une session est **dérivé**, pas stocké :
une session est identifiée de façon unique par (caissier, date), et un
versement porte déjà `received_by` et `created_at`. Ajouter une colonne
`cash_session_id` sur `payments` aurait exigé un backfill et créé deux
sources de vérité pouvant diverger.
"""

import enum
from datetime import date as date_type
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Numeric, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, ValueEnum

if TYPE_CHECKING:
    from app.models.user import User


class CashSessionStatus(str, enum.Enum):
    OPEN = "open"
    # Clôturée par le caissier, qui a compté son tiroir : `counted_amount` et
    # `variance` sont renseignés, et l'écart engage celui qui l'a signé.
    CLOSED = "closed"
    # Clôturée d'office à minuit parce que personne ne l'avait clôturée. La
    # journée est verrouillée pour que la comptabilité du lendemain reparte
    # propre, mais PERSONNE N'A COMPTÉ : `counted_amount` et `variance`
    # restent nuls. Un troisième état plutôt qu'un drapeau à côté de `closed`
    # parce que tout le code qui lit ce statut décide quelque chose — bloquer
    # un encaissement, compter une caisse au point journalier, afficher un
    # écart. Un drapeau les laisserait tous traiter en silence une journée
    # non comptée comme une journée comptée dont l'écart vaudrait zéro.
    AUTO_CLOSED = "auto_closed"


# Journées verrouillées : plus aucun encaissement ni annulation dessus. Écrit
# une fois ici plutôt que comparé à `CLOSED` sur chaque site d'appel, sinon la
# clôture d'office rouvrirait en silence toutes les gardes existantes.
LOCKED_STATUSES: frozenset[str] = frozenset(
    {CashSessionStatus.CLOSED.value, CashSessionStatus.AUTO_CLOSED.value}
)


def is_locked(status: str | CashSessionStatus) -> bool:
    """Accepte l'énum comme la chaîne : SQLAlchemy rend l'un ou l'autre."""
    return str(getattr(status, "value", status)) in LOCKED_STATUSES


class CashSession(Base, TimestampMixin):
    """Journée de caisse d'un caissier.

    Ouverte paresseusement au premier encaissement du jour : obliger le
    caissier à « ouvrir sa caisse » avant de pouvoir encaisser créerait un
    blocage au guichet le matin, avec une file d'attente devant lui.

    La clôture est en revanche un geste explicite : le caissier compte ses
    espèces, saisit le montant, et le système affiche l'écart avec le
    théorique. C'est ce geste qui verrouille la journée.

    Une journée oubliée est clôturée d'office à minuit (`auto_closed`) pour
    que la comptabilité du lendemain reparte sur une caisse propre. Le
    théorique est figé comme sur une clôture normale, mais le montant compté
    reste vide et l'écart inconnu : signer un caissier sur un chiffre qu'il
    n'a pas produit serait un faux. Il régularise le lendemain.
    """

    __tablename__ = "cash_sessions"
    __table_args__ = (
        UniqueConstraint("cashier_user_id", "business_date", name="uq_cash_session_cashier_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    cashier_user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    business_date: Mapped[date_type] = mapped_column(Date, nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        ValueEnum(CashSessionStatus, name="cash_session_status"),
        nullable=False,
        default=CashSessionStatus.OPEN,
        index=True,
    )
    opened_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Espèces réellement comptées dans le tiroir par le caissier.
    counted_amount: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    # Espèces théoriques calculées AU MOMENT de la clôture. Figé : recalculer
    # après coup ferait bouger un écart déjà constaté et signé.
    expected_amount: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    # counted - expected. Négatif = manquant, positif = excédent. Reste NUL sur
    # une clôture d'office : l'écart y est INCONNU, et écrire zéro affirmerait
    # que le tiroir tombait juste alors que personne ne l'a ouvert.
    variance: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)

    # Horodatage du comptage saisi APRÈS une clôture d'office. Renseigné, il
    # dit à la fois « cette journée a été clôturée d'office » et « le caissier
    # a régularisé le tel jour » — deux faits qu'un statut seul perdrait, la
    # session repassant alors en `closed`.
    regularized_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    cashier: Mapped["User"] = relationship("User", foreign_keys=[cashier_user_id])
