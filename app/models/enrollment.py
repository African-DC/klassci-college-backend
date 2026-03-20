"""Modèles d'inscription : Enrollment, Document, StudentOption."""

from __future__ import annotations

import enum
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Enum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin

if TYPE_CHECKING:
    from app.models.academic import AcademicYear, Class
    from app.models.fee import EnrollmentFee, OptionalFeeOption
    from app.models.user import Student


class EnrollmentStatus(str, enum.Enum):
    PROSPECT = "prospect"
    EN_VALIDATION = "en_validation"
    VALIDE = "valide"
    REJETE = "rejete"
    ANNULE = "annule"


class Enrollment(Base, TimestampMixin):
    """Inscription d'un élève dans une classe pour une année scolaire."""

    __tablename__ = "enrollments"
    __table_args__ = (UniqueConstraint("student_id", "academic_year_id", name="uq_enrollment_student_year"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    student_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("students.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    class_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("classes.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    academic_year_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("academic_years.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(
        Enum(EnrollmentStatus, name="enrollment_status"),
        nullable=False,
        default=EnrollmentStatus.PROSPECT,
        index=True,
    )
    created_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    student: Mapped[Student] = relationship(back_populates="enrollments")
    class_: Mapped[Class] = relationship(back_populates="enrollments")
    academic_year: Mapped[AcademicYear] = relationship()
    documents: Mapped[list[Document]] = relationship(back_populates="enrollment")
    student_options: Mapped[list[StudentOption]] = relationship(back_populates="enrollment")
    enrollment_fees: Mapped[list[EnrollmentFee]] = relationship(back_populates="enrollment")


class Document(Base, TimestampMixin):
    """Document justificatif lié à une inscription."""

    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    enrollment_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("enrollments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type: Mapped[str] = mapped_column(
        String(100), nullable=False
    )  # "bulletin", "acte_naissance", etc.
    file_url: Mapped[str] = mapped_column(String(500), nullable=False)
    original_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    enrollment: Mapped[Enrollment] = relationship(back_populates="documents")


class StudentOption(Base):
    """Option facultative choisie par un élève (ex : EPS, 2ème langue)."""

    __tablename__ = "student_options"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    enrollment_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("enrollments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    optional_fee_option_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("optional_fee_options.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    enrollment: Mapped[Enrollment] = relationship(back_populates="student_options")
    optional_fee_option: Mapped[OptionalFeeOption] = relationship(back_populates="student_options")
