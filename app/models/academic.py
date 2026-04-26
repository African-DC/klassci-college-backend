"""Modèles académiques : AcademicYear, Level, Series, Class, Subject, Room, SchoolSettings."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin

if TYPE_CHECKING:
    from app.models.enrollment import Enrollment
    from app.models.timetable import TimetableSlot
    from app.models.user import TeacherProfile


# ---------------------------------------------------------------------------
# AcademicYear
# ---------------------------------------------------------------------------


class AcademicYear(Base, TimestampMixin):
    """Année scolaire (ex : 2024-2025)."""

    __tablename__ = "academic_years"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)  # "2024-2025"
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    classes: Mapped[list[Class]] = relationship(back_populates="academic_year")


# ---------------------------------------------------------------------------
# Level & Series
# ---------------------------------------------------------------------------


class Level(Base):
    """Niveau scolaire (ex : 6ème, 5ème, Terminale)."""

    __tablename__ = "levels"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    series: Mapped[list[Series]] = relationship(back_populates="level")
    classes: Mapped[list[Class]] = relationship(back_populates="level")


class Series(Base):
    """Série de lycée (ex : A1, C, D). Applicable uniquement au lycée."""

    __tablename__ = "series"
    __table_args__ = (UniqueConstraint("level_id", "name"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    level_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("levels.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(20), nullable=False)  # "A1", "C", "D"

    level: Mapped[Level] = relationship(back_populates="series")
    classes: Mapped[list[Class]] = relationship(back_populates="series")


# ---------------------------------------------------------------------------
# Room
# ---------------------------------------------------------------------------


class Room(Base, TimestampMixin):
    """Salle de classe ou laboratoire."""

    __tablename__ = "rooms"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    room_type: Mapped[str] = mapped_column(String(30), nullable=False, server_default="classroom")

    classes: Mapped[list[Class]] = relationship(back_populates="room")
    timetable_slots: Mapped[list[TimetableSlot]] = relationship(back_populates="room")


# ---------------------------------------------------------------------------
# Class
# ---------------------------------------------------------------------------


class Class(Base, TimestampMixin):
    """Classe scolaire (ex : Terminale C, 6ème A)."""

    __tablename__ = "classes"
    __table_args__ = (UniqueConstraint("name", "academic_year_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    level_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("levels.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    series_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("series.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    academic_year_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("academic_years.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    room_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("rooms.id", ondelete="SET NULL"), nullable=True, index=True
    )
    max_students: Mapped[int] = mapped_column(Integer, nullable=False, default=40)

    level: Mapped[Level] = relationship(back_populates="classes")
    series: Mapped[Series | None] = relationship(back_populates="classes")
    academic_year: Mapped[AcademicYear] = relationship(back_populates="classes")
    room: Mapped[Room | None] = relationship(back_populates="classes")
    enrollments: Mapped[list[Enrollment]] = relationship(back_populates="class_")
    timetable_slots: Mapped[list[TimetableSlot]] = relationship(back_populates="class_")


# ---------------------------------------------------------------------------
# Subject
# ---------------------------------------------------------------------------


class Subject(Base, TimestampMixin):
    """Matière enseignée."""

    __tablename__ = "subjects"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    level_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("levels.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    series_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("series.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    coefficient: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    hours_per_week: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    color: Mapped[str | None] = mapped_column(String(20), nullable=True)
    teacher_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("teacher_profiles.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    level: Mapped[Level | None] = relationship(foreign_keys=[level_id])
    series: Mapped[Series | None] = relationship(foreign_keys=[series_id])
    teacher: Mapped[TeacherProfile | None] = relationship(foreign_keys=[teacher_id])
    timetable_slots: Mapped[list[TimetableSlot]] = relationship(back_populates="subject")


# ---------------------------------------------------------------------------
# SchoolSettings (singleton par tenant)
# ---------------------------------------------------------------------------


class SchoolSettings(Base, TimestampMixin):
    """Paramètres de l'établissement (singleton par tenant)."""

    __tablename__ = "school_settings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    school_name: Mapped[str] = mapped_column(String(200), nullable=False)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    logo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    ministry_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    enrollment_number_pattern: Mapped[str | None] = mapped_column(String(200), nullable=True)
    enrollment_number_counter: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Timetable generation settings
    slot_duration_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=60, server_default="60"
    )
    day_start_hour: Mapped[int] = mapped_column(
        Integer, nullable=False, default=7, server_default="7"
    )
    day_end_hour: Mapped[int] = mapped_column(
        Integer, nullable=False, default=17, server_default="17"
    )
