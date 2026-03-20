"""Modèles de frais scolaires : FeeCategory, FeeVariant, OptionalFeeOption, EnrollmentFee, Payment."""

from __future__ import annotations

import enum
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Enum, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin

if TYPE_CHECKING:
    from app.models.academic import AcademicYear, Class
    from app.models.enrollment import Enrollment, StudentOption


class PaymentMethod(str, enum.Enum):
    CASH = "cash"
    MOBILE_MONEY = "mobile_money"
    BANK_TRANSFER = "bank_transfer"
    CHEQUE = "cheque"


class PaymentStatus(str, enum.Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    REFUNDED = "refunded"


class EnrollmentFeeStatus(str, enum.Enum):
    PENDING = "pending"
    PARTIAL = "partial"
    PAID = "paid"
    WAIVED = "waived"


# ---------------------------------------------------------------------------
# FeeCategory
# ---------------------------------------------------------------------------


class FeeCategory(Base, TimestampMixin):
    """Catégorie de frais (ex : Inscription, Scolarité T1, Tenue scolaire)."""

    __tablename__ = "fee_categories"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    variants: Mapped[list[FeeVariant]] = relationship(back_populates="category")


# ---------------------------------------------------------------------------
# FeeVariant — montant applicable à une classe / année
# ---------------------------------------------------------------------------


class FeeVariant(Base, TimestampMixin):
    """Montant d'une catégorie de frais pour une classe et une année scolaire."""

    __tablename__ = "fee_variants"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    fee_category_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("fee_categories.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    class_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("classes.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    academic_year_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("academic_years.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    category: Mapped[FeeCategory] = relationship(back_populates="variants")
    class_: Mapped[Class | None] = relationship()
    academic_year: Mapped[AcademicYear] = relationship()
    enrollment_fees: Mapped[list[EnrollmentFee]] = relationship(back_populates="fee_variant")


# ---------------------------------------------------------------------------
# OptionalFeeOption — frais optionnels (ex : transport, cantine)
# ---------------------------------------------------------------------------


class OptionalFeeOption(Base, TimestampMixin):
    """Option de frais facultatifs proposée aux élèves."""

    __tablename__ = "optional_fee_options"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    academic_year_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("academic_years.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    academic_year: Mapped[AcademicYear] = relationship()
    student_options: Mapped[list[StudentOption]] = relationship(
        back_populates="optional_fee_option"
    )


# ---------------------------------------------------------------------------
# EnrollmentFee — frais dûs par une inscription
# ---------------------------------------------------------------------------


class EnrollmentFee(Base, TimestampMixin):
    """Frais applicable à une inscription spécifique."""

    __tablename__ = "enrollment_fees"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    enrollment_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("enrollments.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    fee_variant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("fee_variants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    status: Mapped[str] = mapped_column(
        Enum(EnrollmentFeeStatus, name="enrollment_fee_status"),
        nullable=False,
        default=EnrollmentFeeStatus.PENDING,
        index=True,
    )

    enrollment: Mapped[Enrollment] = relationship(back_populates="enrollment_fees")
    fee_variant: Mapped[FeeVariant] = relationship(back_populates="enrollment_fees")
    payments: Mapped[list[Payment]] = relationship(back_populates="enrollment_fee")


# ---------------------------------------------------------------------------
# Payment
# ---------------------------------------------------------------------------


class Payment(Base, TimestampMixin):
    """Paiement d'un frais d'inscription."""

    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    enrollment_fee_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("enrollment_fees.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    method: Mapped[str] = mapped_column(Enum(PaymentMethod, name="payment_method"), nullable=False)
    status: Mapped[str] = mapped_column(
        Enum(PaymentStatus, name="payment_status"),
        nullable=False,
        default=PaymentStatus.PENDING,
        index=True,
    )
    reference: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    received_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    enrollment_fee: Mapped[EnrollmentFee] = relationship(back_populates="payments")
