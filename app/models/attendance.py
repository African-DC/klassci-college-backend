"""Modèles de présence : AttendanceContext, AttendanceRecord, TeacherSessionAttendance."""

from __future__ import annotations

import enum
from datetime import date, datetime, time
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, String, Text, Time
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, ValueEnum

if TYPE_CHECKING:
    from app.models.academic import AcademicYear
    from app.models.timetable import TimetableSlot
    from app.models.user import Student, TeacherProfile, User


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


# ---------------------------------------------------------------------------
# Teacher session attendance — pointage enseignant par créneau EDT
# ---------------------------------------------------------------------------


class TeacherAttendanceStatus(str, enum.Enum):
    """Statut de présence d'un enseignant à son créneau EDT.

    Modèle ivoirien : prof se déplace entre classes, peut rater un cours
    spécifique sans rater toute la journée. Granularité = slot EDT
    (référence rule `klassci-rooms-ivory-coast-model.md`).
    """

    PRESENT = "present"
    ABSENT_EXCUSED = "absent_excused"
    ABSENT_UNEXCUSED = "absent_unexcused"
    LATE = "late"


class TeacherSessionAttendance(Base, TimestampMixin):
    """Pointage d'une séance enseignant.

    Granularité = un row par (teacher, slot, date). Un slot EDT récurrent
    (lundi 10h-11h Maths 6ème B) produit 1 row par instance datée.
    `slot_id` nullable : permet une absence "hors EDT" (réunion DREN,
    formation, congé maladie sans slot précis ce jour-là).

    Workflow validation hybride (Marcel 2026-05-19) :
    - Admin/staff saisit directement → `is_validated=True` instantané
    - Prof se déclare lui-même → `is_validated=False`, admin valide après
    """

    __tablename__ = "teacher_session_attendance"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # Qui (teacher) + Quand (slot + date) + Où (académique)
    teacher_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("teacher_profiles.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    slot_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("timetable_slots.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    academic_year_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("academic_years.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    # Quoi
    status: Mapped[str] = mapped_column(
        ValueEnum(TeacherAttendanceStatus, name="teacher_attendance_status"),
        nullable=False,
        default=TeacherAttendanceStatus.PRESENT,
        index=True,
    )
    late_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Workflow validation
    declared_by_user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    declared_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    is_validated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    validated_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    validated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    teacher: Mapped[TeacherProfile] = relationship(foreign_keys=[teacher_id])
    slot: Mapped[TimetableSlot | None] = relationship(foreign_keys=[slot_id])
    academic_year: Mapped[AcademicYear] = relationship()
    declared_by: Mapped[User] = relationship(foreign_keys=[declared_by_user_id])
    validated_by: Mapped[User | None] = relationship(foreign_keys=[validated_by_user_id])
