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
    CLOSED = "closed"


class CashSession(Base, TimestampMixin):
    """Journée de caisse d'un caissier.

    Ouverte paresseusement au premier encaissement du jour : obliger le
    caissier à « ouvrir sa caisse » avant de pouvoir encaisser créerait un
    blocage au guichet le matin, avec une file d'attente devant lui.

    La clôture est en revanche un geste explicite : le caissier compte ses
    espèces, saisit le montant, et le système affiche l'écart avec le
    théorique. C'est ce geste qui verrouille la journée.
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
    # counted - expected. Négatif = manquant, positif = excédent.
    variance: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    cashier: Mapped["User"] = relationship("User", foreign_keys=[cashier_user_id])
