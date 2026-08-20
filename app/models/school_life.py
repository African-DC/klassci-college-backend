"""Modèles de vie scolaire : convocations de parents, autorisations de rattrapage.

Deux registres que l'éducateur tient aujourd'hui sur un cahier à souches. Les
mettre en base ne sert pas à archiver du papier : c'est ce qui permet de
répondre aux deux questions posées en conseil de classe — qui a été convoqué
ce trimestre, et qui est venu — sans feuilleter trois mois de talons.

Le billet d'entrée n'a volontairement pas de table : il ferme une absence
déjà saisie dans `attendance_records`, et créer un registre parallèle
ferait diverger deux vérités sur la même journée.
"""

from __future__ import annotations

import enum
from datetime import date, datetime, time
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, ValueEnum

if TYPE_CHECKING:
    from app.models.academic import AcademicYear
    from app.models.grade import Evaluation
    from app.models.user import Parent, Student, User


class SummonsOutcome(str, enum.Enum):
    """Suite donnée à une convocation.

    `PENDING` n'est pas « en attente de réponse » mais « non renseigné » :
    tant que l'éducateur n'a rien noté, on ne sait pas si le parent est venu.
    Compter ces lignes comme des absences fausserait le taux de présence.
    """

    PENDING = "pending"
    ATTENDED = "attended"
    MISSED = "missed"


class ParentSummons(Base, TimestampMixin):
    """Une convocation de tuteur légal, et la suite qui lui a été donnée."""

    __tablename__ = "parent_summons"
    __table_args__ = (
        CheckConstraint("trimester >= 1 AND trimester <= 3", name="ck_parent_summons_trimester"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    student_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("students.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    # Le tuteur convoqué quand il a une fiche dans le logiciel. Beaucoup de
    # familles n'en ont pas encore : `parent_name` recueille alors le nom
    # dicté au guichet, pour que le document reste nominatif.
    parent_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("parents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    parent_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    academic_year_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("academic_years.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    trimester: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    summons_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    summons_time: Mapped[time] = mapped_column(Time, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    issued_by_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    # Référence du document scellé, pour rapprocher une convocation du papier
    # que la famille présente au portail.
    reference: Mapped[str | None] = mapped_column(String(60), nullable=True, index=True)

    outcome: Mapped[str] = mapped_column(
        ValueEnum(SummonsOutcome, name="summons_outcome"),
        nullable=False,
        default=SummonsOutcome.PENDING,
        index=True,
    )
    outcome_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    outcome_recorded_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    outcome_recorded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    student: Mapped[Student] = relationship()
    parent: Mapped[Parent | None] = relationship()
    academic_year: Mapped[AcademicYear] = relationship()
    issued_by: Mapped[User] = relationship(foreign_keys=[issued_by_user_id])
    outcome_recorded_by: Mapped[User | None] = relationship(
        foreign_keys=[outcome_recorded_by_user_id]
    )


class RetakeAuthorization(Base, TimestampMixin):
    """Billet d'annulation de zéro : la fenêtre pendant laquelle un élève rattrape.

    L'autorisation rouvre les évaluations visées ; elle ne porte jamais de
    note. La note de rattrapage reste saisie par l'enseignant, sur sa feuille,
    comme n'importe quelle autre — c'est ce qui rend la moyenne défendable
    devant un conseil de classe.
    """

    __tablename__ = "retake_authorizations"
    __table_args__ = (
        CheckConstraint(
            "trimester >= 1 AND trimester <= 3", name="ck_retake_authorizations_trimester"
        ),
        CheckConstraint("period_end >= period_start", name="ck_retake_authorizations_period_order"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    student_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("students.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    academic_year_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("academic_years.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    trimester: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    issued_by_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    reference: Mapped[str | None] = mapped_column(String(60), nullable=True, index=True)

    student: Mapped[Student] = relationship()
    academic_year: Mapped[AcademicYear] = relationship()
    issued_by: Mapped[User] = relationship(foreign_keys=[issued_by_user_id])
    targets: Mapped[list[RetakeAuthorizationEvaluation]] = relationship(
        back_populates="authorization", cascade="all, delete-orphan"
    )


class RetakeAuthorizationEvaluation(Base, TimestampMixin):
    """Une évaluation précise rouverte par un billet d'annulation de zéro."""

    __tablename__ = "retake_authorization_evaluations"
    __table_args__ = (
        UniqueConstraint(
            "authorization_id", "evaluation_id", name="uq_retake_authorization_evaluation"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    authorization_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("retake_authorizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    evaluation_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("evaluations.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    authorization: Mapped[RetakeAuthorization] = relationship(back_populates="targets")
    evaluation: Mapped[Evaluation] = relationship()
