"""Modèles de notes : Evaluation, Grade, Bulletin, SubjectAverage."""

from __future__ import annotations

import enum
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, ValueEnum

if TYPE_CHECKING:
    from app.models.academic import AcademicYear, Class, Subject
    from app.models.user import Student, TeacherProfile


class EvaluationType(str, enum.Enum):
    CONTROLE = "controle"
    DEVOIR = "devoir"
    EXAMEN = "examen"
    ORAL = "oral"


class GradeStatus(str, enum.Enum):
    """Cycle de vie d'une note.

    Trois situations que `pending` confondait, alors que le conseil de classe
    les traite differemment : la note pas encore saisie, l'eleve absent le jour
    de l'epreuve (zero d'office, la note compte) et l'epreuve rouverte par un
    billet d'annulation de zero, en attente de la note de rattrapage que seul
    l'enseignant saisira.
    """

    PENDING = "pending"
    ENTERED = "entered"
    ABSENT = "absent"
    RETAKE_ALLOWED = "retake_allowed"


# Statuts dont la valeur entre dans les moyennes. Le zero d'office compte comme
# une note : l'exclure reviendrait a recompenser l'absence. Constante partagee
# pour que bulletins, rapports et score enseignant ne divergent pas.
COUNTED_GRADE_STATUSES: tuple[GradeStatus, ...] = (GradeStatus.ENTERED, GradeStatus.ABSENT)

# Statuts qu'un enregistrement de feuille de notes laissee vide ne doit pas
# ecraser : un rattrapage autorise et pas encore note doit survivre a la
# sauvegarde suivante, sinon l'autorisation disparait dans le dos de tout le
# monde et l'eleve retombe a zero.
STICKY_GRADE_STATUSES: tuple[GradeStatus, ...] = (
    GradeStatus.ABSENT,
    GradeStatus.RETAKE_ALLOWED,
)


class Mention(str, enum.Enum):
    TRES_BIEN = "TB"  # >= 16
    BIEN = "B"  # >= 14
    ASSEZ_BIEN = "AB"  # >= 12
    PASSABLE = "P"  # >= 10
    MEDIOCRE = "M"  # < 10


class CouncilDecision(str, enum.Enum):
    PASSAGE = "passage"
    REPECHAGE = "repechage"
    REDOUBLEMENT = "redoublement"
    EXCLUSION = "exclusion"


class Evaluation(Base, TimestampMixin):
    """Évaluation (contrôle, devoir, examen) pour une classe."""

    __tablename__ = "evaluations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    type: Mapped[str] = mapped_column(
        ValueEnum(EvaluationType, name="evaluation_type"), nullable=False, index=True
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
    __table_args__ = (CheckConstraint("value >= 0 AND value <= 20", name="ck_grade_value_range"),)

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
        ValueEnum(GradeStatus, name="grade_status"),
        nullable=False,
        default=GradeStatus.PENDING,
        index=True,
    )
    # Audit trail : qui a saisi cette note (peut être un admin déléguant pour un prof
    # qui ne maîtrise pas l'outil — workflow réel CI). NULL pour les notes legacy
    # antérieures à la migration 0019 ou si le current_user n'est pas tracé.
    entered_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
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
    mention: Mapped[str | None] = mapped_column(ValueEnum(Mention, name="mention"), nullable=True)
    file_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    teacher_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    council_decision: Mapped[str | None] = mapped_column(
        ValueEnum(CouncilDecision, name="council_decision"), nullable=True
    )

    student: Mapped[Student] = relationship()
    class_: Mapped[Class] = relationship()
    academic_year: Mapped[AcademicYear] = relationship()
    subject_averages: Mapped[list[SubjectAverage]] = relationship(back_populates="bulletin")


class SubjectAverage(Base, TimestampMixin):
    """Moyenne par matière pour un bulletin trimestriel."""

    __tablename__ = "subject_averages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    bulletin_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("bulletins.id", ondelete="CASCADE"), nullable=False, index=True
    )
    subject_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("subjects.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    student_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("students.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    trimester: Mapped[int] = mapped_column(Integer, nullable=False)
    average: Mapped[Decimal] = mapped_column(Numeric(4, 2), nullable=False)
    coefficient: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    bulletin: Mapped[Bulletin] = relationship(back_populates="subject_averages")
    subject: Mapped[Subject] = relationship()
    student: Mapped[Student] = relationship()


class CouncilMinutes(Base, TimestampMixin):
    """Procès-verbal du conseil de classe."""

    __tablename__ = "council_minutes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    class_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("classes.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    academic_year_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("academic_years.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    trimester: Mapped[int] = mapped_column(Integer, nullable=False)
    main_teacher_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    director_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    dren_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    class_: Mapped[Class] = relationship()
    academic_year: Mapped[AcademicYear] = relationship()
    decisions: Mapped[list[CouncilStudentDecision]] = relationship(back_populates="council_minutes")


class CouncilStudentDecision(Base, TimestampMixin):
    """Décision du conseil pour un élève."""

    __tablename__ = "council_student_decisions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    council_minutes_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("council_minutes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    student_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("students.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    average: Mapped[Decimal | None] = mapped_column(Numeric(4, 2), nullable=True)
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    absence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    auto_decision: Mapped[str] = mapped_column(String(50), nullable=False)
    final_decision: Mapped[str | None] = mapped_column(String(50), nullable=True)
    override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    council_minutes: Mapped[CouncilMinutes] = relationship(back_populates="decisions")
    student: Mapped[Student] = relationship()
