"""Modèles d'inscription : Enrollment, Document, StudentOption."""

from __future__ import annotations

import enum
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.archivable import ArchivableMixin
from app.models.base import TimestampMixin, ValueEnum

if TYPE_CHECKING:
    from app.models.academic import AcademicYear, Class
    from app.models.fee import EnrollmentFee, OptionalFeeOption, Payment
    from app.models.user import Student


class EnrollmentStatus(str, enum.Enum):
    PROSPECT = "prospect"
    EN_VALIDATION = "en_validation"
    VALIDE = "valide"
    REJETE = "rejete"
    ANNULE = "annule"


class AssignmentStatus(str, enum.Enum):
    """Statut d'affectation d'un eleve par l'Etat.

    En Cote d'Ivoire, un eleve affecte dans un etablissement prive est
    subventionne : sa famille paie sensiblement moins qu'un non affecte. Le
    reaffecte — reoriente vers un autre etablissement — reste pris en charge,
    donc paie comme un affecte ; on garde neanmoins la distinction, que les
    dossiers du ministere et le rapport de fin de trimestre reclament.

    L'affectation vaut pour une annee et un etablissement donnes : elle vit
    donc sur l'inscription, pas sur l'eleve. Un redoublant peut la perdre.
    """

    AFFECTE = "affecte"
    REAFFECTE = "reaffecte"
    NON_AFFECTE = "non_affecte"

    @property
    def is_subsidised(self) -> bool:
        return self in (AssignmentStatus.AFFECTE, AssignmentStatus.REAFFECTE)


class Enrollment(Base, TimestampMixin, ArchivableMixin):
    """Inscription d'un élève dans une classe pour une année scolaire."""

    __tablename__ = "enrollments"
    __table_args__ = (
        UniqueConstraint("student_id", "academic_year_id", name="uq_enrollment_student_year"),
    )

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
    # `None` = pas encore renseigne. On ne devine pas : un defaut a
    # « non affecte » ferait basculer des familles existantes vers le tarif
    # plein sans que personne ne l'ait decide.
    assignment_status: Mapped[str | None] = mapped_column(
        ValueEnum(AssignmentStatus, name="assignment_status"),
        nullable=True,
        index=True,
    )
    # Numero de la decision d'affectation, reclame par le rapport DEEP.
    assignment_decision_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(
        ValueEnum(EnrollmentStatus, name="enrollment_status"),
        nullable=False,
        default=EnrollmentStatus.PROSPECT,
        index=True,
    )
    created_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    student: Mapped[Student] = relationship(back_populates="enrollments")
    class_: Mapped[Class] = relationship(back_populates="enrollments")
    academic_year: Mapped[AcademicYear] = relationship()
    documents: Mapped[list[Document]] = relationship(back_populates="enrollment")
    student_options: Mapped[list[StudentOption]] = relationship(back_populates="enrollment")
    enrollment_fees: Mapped[list[EnrollmentFee]] = relationship(back_populates="enrollment")
    # `passive_deletes` laisse la clé étrangère décider : elle est en RESTRICT,
    # donc supprimer une inscription qui porte encore des versements échoue —
    # et c'est voulu. Détacher les versements doit rester un geste explicite,
    # journalisé, pas un effet de bord silencieux de l'ORM.
    payments: Mapped[list[Payment]] = relationship(
        back_populates="enrollment", passive_deletes=True
    )


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
