"""Modèles emploi du temps : Timetable, TimetableSlot, TeacherAvailability."""

from __future__ import annotations

import enum
from datetime import time
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, CheckConstraint, ForeignKey, String, Time
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, ValueEnum

if TYPE_CHECKING:
    from app.models.academic import AcademicYear, Class, Room, Subject
    from app.models.user import TeacherProfile


class DayOfWeek(str, enum.Enum):
    MONDAY = "monday"
    TUESDAY = "tuesday"
    WEDNESDAY = "wednesday"
    THURSDAY = "thursday"
    FRIDAY = "friday"
    SATURDAY = "saturday"


class Timetable(Base, TimestampMixin):
    """En-tête d'un emploi du temps généré pour une classe."""

    __tablename__ = "timetables"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    class_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("classes.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    academic_year_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("academic_years.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    class_: Mapped[Class] = relationship()
    academic_year: Mapped[AcademicYear] = relationship()
    slots: Mapped[list[TimetableSlot]] = relationship(back_populates="timetable")


class TimetableSlot(Base, TimestampMixin):
    """Créneau horaire dans l'emploi du temps."""

    __tablename__ = "timetable_slots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    timetable_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("timetables.id", ondelete="SET NULL"), nullable=True, index=True
    )
    class_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("classes.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    teacher_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("teacher_profiles.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    subject_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("subjects.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    room_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("rooms.id", ondelete="SET NULL"), nullable=True, index=True
    )
    academic_year_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("academic_years.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    day: Mapped[str] = mapped_column(
        ValueEnum(DayOfWeek, name="day_of_week"), nullable=False, index=True
    )
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)

    timetable: Mapped[Timetable | None] = relationship(back_populates="slots")
    class_: Mapped[Class] = relationship(back_populates="timetable_slots")
    teacher: Mapped[TeacherProfile] = relationship()
    subject: Mapped[Subject] = relationship(back_populates="timetable_slots")
    room: Mapped[Room | None] = relationship(back_populates="timetable_slots")
    academic_year: Mapped[AcademicYear] = relationship()


class TeacherAvailability(Base):
    """Disponibilités déclarées d'un enseignant."""

    __tablename__ = "teacher_availabilities"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    teacher_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("teacher_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    day: Mapped[str] = mapped_column(ValueEnum(DayOfWeek, name="day_of_week"), nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    preferred: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )

    teacher: Mapped[TeacherProfile] = relationship()


class ScheduleEvent(Base, TimestampMixin):
    """Recurring non-curricular school event, scoped to a tenant DB and school year."""

    __tablename__ = "schedule_events"
    __table_args__ = (CheckConstraint("end_time > start_time", name="valid_time_range"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    academic_year_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("academic_years.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    class_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("classes.id", ondelete="CASCADE"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    category: Mapped[str] = mapped_column(String(24), nullable=False)
    blocks_courses: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    day: Mapped[str] = mapped_column(ValueEnum(DayOfWeek, name="day_of_week"), nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
