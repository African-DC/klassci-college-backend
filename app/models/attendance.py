"""Modèles de présence : AttendanceContext, AttendanceRecord."""

from __future__ import annotations

import enum
from datetime import date, time
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Date, ForeignKey, String, Time
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, ValueEnum

if TYPE_CHECKING:
    from app.models.academic import AcademicYear
    from app.models.user import Student


class AttendanceEntityType(str, enum.Enum):
    CLASS = "class"
    EXAM = "exam"


class AttendanceStatus(str, enum.Enum):
    PRESENT = "present"
    ABSENT = "absent"
    LATE = "late"
    EXCUSED = "excused"


class AttendanceSource(str, enum.Enum):
    MANUAL = "manual"
    QR_CODE = "qr_code"
    BIOMETRIC = "biometric"


class AttendanceContext(Base, TimestampMixin):
    """Contexte de présence : séance de cours ou examen."""

    __tablename__ = "attendance_contexts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    entity_type: Mapped[str] = mapped_column(
        ValueEnum(AttendanceEntityType, name="attendance_entity_type"), nullable=False, index=True
    )
    context_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, index=True
    )  # class_id or exam_id
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    academic_year_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("academic_years.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    academic_year: Mapped[AcademicYear] = relationship()
    records: Mapped[list[AttendanceRecord]] = relationship(back_populates="context")


class AttendanceRecord(Base, TimestampMixin):
    """Enregistrement de présence d'un élève."""

    __tablename__ = "attendance_records"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    context_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("attendance_contexts.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    student_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("students.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(
        ValueEnum(AttendanceStatus, name="attendance_status"),
        nullable=False,
        default=AttendanceStatus.ABSENT,
        index=True,
    )
    time_in: Mapped[time | None] = mapped_column(Time, nullable=True)
    time_out: Mapped[time | None] = mapped_column(Time, nullable=True)
    source: Mapped[str] = mapped_column(
        ValueEnum(AttendanceSource, name="attendance_source"),
        nullable=False,
        default=AttendanceSource.MANUAL,
    )
    notes: Mapped[str | None] = mapped_column(String(255), nullable=True)

    context: Mapped[AttendanceContext] = relationship(back_populates="records")
    student: Mapped[Student] = relationship()
