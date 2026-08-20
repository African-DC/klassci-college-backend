"""Données réclamées par le rapport de fin de trimestre de la DEEP.

La DEEP (Direction de l'Encadrement des Établissements Privés) impose aux
établissements privés un canevas de 27 tableaux. Quatre d'entre eux portent
sur des informations que KLASSCI ne collectait nulle part : les visites de
classe, les formations d'enseignants, les transferts et réintégrations, et
les bourses. Ces quatre tables comblent exactement ces trous.

Pourquoi des tables dédiées plutôt que des colonnes sur l'inscription : une
inscription porte un seul état à un instant donné, alors qu'un même élève
peut recevoir plusieurs bourses successives, et qu'un même enseignant peut
être visité dix fois dans le trimestre. Écraser ces événements dans une
colonne ferait perdre les dates, or le canevas les réclame explicitement.
"""

from __future__ import annotations

import enum
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Date, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, ValueEnum

if TYPE_CHECKING:
    from app.models.academic import AcademicYear, Class, Subject
    from app.models.enrollment import Enrollment
    from app.models.user import TeacherProfile


class ScholarshipKind(str, enum.Enum):
    """Nature de la bourse — le canevas ne distingue que ces deux niveaux."""

    BOURSE_ENTIERE = "bourse_entiere"
    DEMI_BOURSE = "demi_bourse"


class TransferKind(str, enum.Enum):
    """Un élève arrive d'ailleurs, ou revient après une interruption.

    Le canevas range les deux dans le même tableau parce que la pièce
    justificative est la même : une décision numérotée de l'administration.
    """

    TRANSFERT = "transfert"
    REINTEGRATION = "reintegration"


class ClassVisit(Base, TimestampMixin):
    """Visite de classe d'un enseignant par la direction des études.

    Le canevas agrège par enseignant et par discipline (« nombre de visites »
    et « dates »), mais on stocke une ligne par visite : c'est la seule façon
    de restituer les dates, et l'agrégat se recalcule à la lecture.
    """

    __tablename__ = "class_visits"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    teacher_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("teacher_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    subject_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("subjects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    class_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("classes.id", ondelete="SET NULL"), nullable=True, index=True
    )
    academic_year_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("academic_years.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    visit_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    visitor_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    observations: Mapped[str | None] = mapped_column(Text, nullable=True)

    teacher: Mapped[TeacherProfile] = relationship()
    subject: Mapped[Subject | None] = relationship()
    class_: Mapped[Class | None] = relationship()
    academic_year: Mapped[AcademicYear] = relationship()


class TeacherTraining(Base, TimestampMixin):
    """Participation d'un enseignant à une formation.

    Une ligne par couple (enseignant, formation) : le canevas compte les
    « enseignants formés » autant que les formations, donc il faut les deux
    dimensions.
    """

    __tablename__ = "teacher_trainings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    teacher_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("teacher_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    subject_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("subjects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    academic_year_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("academic_years.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    # Discipline en clair : certaines formations sont transversales (« gestion
    # de classe », « numérique éducatif ») et ne se rattachent à aucune matière
    # du référentiel. Sans ce champ elles disparaîtraient du tableau.
    discipline_label: Mapped[str | None] = mapped_column(String(150), nullable=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    training_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    observations: Mapped[str | None] = mapped_column(Text, nullable=True)

    teacher: Mapped[TeacherProfile] = relationship()
    subject: Mapped[Subject | None] = relationship()
    academic_year: Mapped[AcademicYear] = relationship()


class StudentTransfer(Base, TimestampMixin):
    """Transfert entrant ou réintégration, rattaché à l'inscription concernée.

    Le rattachement se fait sur l'inscription et non sur l'élève : l'année et
    la classe d'arrivée font partie de l'information que le canevas réclame,
    et elles vivent sur l'inscription.
    """

    __tablename__ = "student_transfers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    enrollment_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("enrollments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(
        ValueEnum(TransferKind, name="transfer_kind"),
        nullable=False,
        default=TransferKind.TRANSFERT,
        index=True,
    )
    origin_school: Mapped[str | None] = mapped_column(String(200), nullable=True)
    decision_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    transfer_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    observations: Mapped[str | None] = mapped_column(Text, nullable=True)

    enrollment: Mapped[Enrollment] = relationship()


class Scholarship(Base, TimestampMixin):
    """Bourse ou demi-bourse accordée à un élève pour une inscription donnée.

    Le montant reste facultatif : beaucoup de bourses ivoiriennes sont des
    exonérations en pourcentage, sans montant notifié à l'établissement.
    Laisser 0 par défaut ferait croire à une bourse sans valeur.
    """

    __tablename__ = "scholarships"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    enrollment_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("enrollments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(
        ValueEnum(ScholarshipKind, name="scholarship_kind"),
        nullable=False,
        default=ScholarshipKind.BOURSE_ENTIERE,
        index=True,
    )
    provider: Mapped[str | None] = mapped_column(String(200), nullable=True)
    decision_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    granted_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    observations: Mapped[str | None] = mapped_column(Text, nullable=True)

    enrollment: Mapped[Enrollment] = relationship()
