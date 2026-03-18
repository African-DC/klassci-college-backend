"""Modèles de notes : Evaluation, Grade, Bulletin."""

from __future__ import annotations

import enum
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin

if TYPE_CHECKING:
    from app.models.academic import AcademicYear, Class, Subject
    from app.models.user import Student, TeacherProfile


class EvaluationType(str, enum.Enum):
    CONTROLE = "controle"
    DEVOIR = "devoir"
    EXAMEN = "examen"
    ORAL = "oral"


class GradeStatus(str, enum.Enum):
    PENDING = "pending"
    ENTERED = "entered"


class Mention(str, enum.Enum):
    TRES_BIEN = "TB"  # >= 16
    BIEN = "B"  # >= 14
    ASSEZ_BIEN = "AB"  # >= 12
    PASSABLE = "P"  # >= 10
    MEDIOCRE = "M"  # < 10


class Evaluation(Base, TimestampMixin):
    """Évaluation (contrôle, devoir, examen) pour une classe."""

    __tablename__ = "evaluations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    type: Mapped[str] = mapped_column(
        Enum(EvaluationType, name="evaluation_type"), nullable=False, index=True
    )
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    coefficient: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    subject_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("subjects.id", ondelete="RESTRICT"), nullable=False, index=True
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
    academic_year_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("academic_years.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    trimester: Mapped[int] = mapped_column(Integer, nullable=False)  # 1, 2 ou 3

    subject: Mapped[Subject] = relationship()
    class_: Mapped[Class] = relationship()
    teacher: Mapped[TeacherProfile] = relationship()
    academic_year: Mapped[AcademicYear] = relationship()
    grades: Mapped[list[Grade]] = relationship(back_populates="evaluation")


class Grade(Base, TimestampMixin):
    """Note d'un élève pour une évaluation."""

    __tablename__ = "grades"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    evaluation_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("evaluations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    student_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("students.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    # NULL tant que non saisie (status=pending)
    value: Mapped[Decimal | None] = mapped_column(Numeric(4, 2), nullable=True)
    status: Mapped[str] = mapped_column(
        Enum(GradeStatus, name="grade_status"),
        nullable=False,
        default=GradeStatus.PENDING,
        index=True,
    )

    evaluation: Mapped[Evaluation] = relationship(back_populates="grades")
    student: Mapped[Student] = relationship(back_populates="grades")


class Bulletin(Base, TimestampMixin):
    """Bulletin scolaire trimestriel généré pour un élève."""

    __tablename__ = "bulletins"

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
    trimester: Mapped[int] = mapped_column(Integer, nullable=False)  # 1, 2 ou 3
    average: Mapped[Decimal | None] = mapped_column(Numeric(4, 2), nullable=True)
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mention: Mapped[str | None] = mapped_column(Enum(Mention, name="mention"), nullable=True)
    file_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    student: Mapped[Student] = relationship()
    class_: Mapped[Class] = relationship()
    academic_year: Mapped[AcademicYear] = relationship()
