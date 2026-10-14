"""Réduction individualisée sur une ligne de frais, sans toucher à la grille générale."""

from decimal import Decimal

from sqlalchemy import BigInteger, ForeignKey, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin


class EnrollmentFeeDiscount(Base, TimestampMixin):
    __tablename__ = "enrollment_fee_discounts"
    __table_args__ = (
        Index("uq_enrollment_fee_discount", "enrollment_fee_id", unique=True),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    enrollment_fee_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("enrollment_fees.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Montant avant remise, conservé même si la grille générale évolue.
    original_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    kind: Mapped[str] = mapped_column(String(12), nullable=False)
    value: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    granted_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
