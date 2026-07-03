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

    # Class is now universal (no academic_year_id). Listing « classes courantes »
    # passe par JOIN sur Enrollment.academic_year_id côté repo, pas via cette
    # relation qui n'existe plus depuis le refactor #97.

    trimesters: Mapped[list[Trimester]] = relationship(
        back_populates="academic_year",
        cascade="all, delete-orphan",
        order_by="Trimester.order_no",
    )
    holidays: Mapped[list[SchoolHoliday]] = relationship(
        back_populates="academic_year",
        cascade="all, delete-orphan",
        order_by="SchoolHoliday.start_date",
    )


class Trimester(Base, TimestampMixin):
    """Trimestre scolaire scopé à une année académique.

    Le calendrier scolaire ivoirien découpe l'année en 3 trimestres. Chaque
    bulletin, conseil de classe et moyenne périodique se rattache à un
    trimestre. Les dates varient légèrement d'une année à l'autre, d'où
    le scoping par `academic_year_id`.
    """

    __tablename__ = "trimesters"
    __table_args__ = (UniqueConstraint("academic_year_id", "order_no"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    academic_year_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("academic_years.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    label: Mapped[str] = mapped_column(String(50), nullable=False)
    order_no: Mapped[int] = mapped_column(Integer, nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)

    academic_year: Mapped[AcademicYear] = relationship(back_populates="trimesters")


class SchoolHoliday(Base, TimestampMixin):
    """Période de congé ou jour férié scopée à une année académique.

    Contrairement aux trimestres (qui délimitent les périodes d'enseignement),
    un `SchoolHoliday` marque une plage de jours *non travaillés* à l'intérieur
    (ou en marge) de l'année : congés de Toussaint, fêtes religieuses mobiles,
    jour férié isolé (1er mai, fête de l'Indépendance…). Un jour unique se
    représente avec `start_date == end_date`. Les fêtes mobiles variant chaque
    année, ces plages sont saisies par l'établissement, pas figées dans le code.
    """

    __tablename__ = "school_holidays"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    academic_year_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("academic_years.id", ondelete="CASCADE"),
        nullable=False,
    )
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)

    academic_year: Mapped[AcademicYear] = relationship(back_populates="holidays")


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
    """Classe scolaire universelle (ex : Terminale C, 6ème A).

    Refactor #97 : Class est désormais universelle (1 row par classe à vie).
    L'année académique est portée par Enrollment.academic_year_id, pas par Class.
    Les changements rares de max_students/room_id sont audit-loggés via la table
    audit_logs existante (entity_type=class, action=update).
    """

    __tablename__ = "classes"
    __table_args__ = (UniqueConstraint("name"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    level_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("levels.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    series_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("series.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    room_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("rooms.id", ondelete="SET NULL"), nullable=True, index=True
    )
    max_students: Mapped[int] = mapped_column(Integer, nullable=False, default=40)

    level: Mapped[Level] = relationship(back_populates="classes")
    series: Mapped[Series | None] = relationship(back_populates="classes")
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
    # Official documents (PR #105)
    signature_image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    head_master_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    head_master_title: Mapped[str | None] = mapped_column(String(100), nullable=True)
    enrollment_number_pattern: Mapped[str | None] = mapped_column(String(200), nullable=True)
    enrollment_number_counter: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Personnalisation PDF par tenant (migration 0029)
    primary_color: Mapped[str | None] = mapped_column(String(7), nullable=True)
    accent_color: Mapped[str | None] = mapped_column(String(7), nullable=True)
    website: Mapped[str | None] = mapped_column(String(255), nullable=True)
    motto: Mapped[str | None] = mapped_column(String(255), nullable=True)
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
    # Notification settings (canaux + types)
    notify_by_email: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    notify_by_sms: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    notify_grades: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    notify_absences: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    notify_payments: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    notify_enrollment: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    notify_reenrollment: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
