"""Tranches de paiement — grille standard de l'année et échéancier négocié.

Une tranche n'est **pas** une catégorie de frais. Le découpage « Scolarité
Trimestre 1/2/3 » confondait les deux : le trimestre est un moment de
paiement, pas une nature de frais. Ici, les catégories restent des natures
(Inscription, Scolarité, COGES, Tenue, et ce que l'école ajoute) et les
tranches découpent le **total obligatoire** dans le temps.

Deux niveaux :

- `FeeInstallment` — la grille de l'établissement pour une année scolaire,
  exprimée en **pourcentages** du total obligatoire. Un pourcentage suit
  automatiquement une 6e et une Terminale qui n'ont pas les mêmes frais, là
  où des montants fixes se désynchroniseraient au premier changement de tarif.
- `EnrollmentInstallment` — l'échéancier **négocié** avec une famille, en
  montants fixes cette fois, puisqu'il résulte d'un accord précis.

Ni l'un ni l'autre ne touche à l'allocation d'un versement : celle-ci reste
gouvernée par la priorité des catégories. Les tranches ne servent qu'à dire
ce qui est dû à quelle date, donc à calculer un retard honnête.
"""

from datetime import date as date_type
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Date,
    ForeignKey,
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin

if TYPE_CHECKING:
    from app.models.academic import AcademicYear
    from app.models.enrollment import Enrollment


class FeeInstallment(Base, TimestampMixin):
    """Une tranche de la grille standard, en pourcentage du total obligatoire."""

    __tablename__ = "fee_installments"
    __table_args__ = (
        UniqueConstraint("academic_year_id", "position", name="uq_fee_installment_year_position"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    academic_year_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("academic_years.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # Ordre d'échéance. Sert aussi de clé d'unicité avec l'année.
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    # Part du total obligatoire, en pourcentage. La somme de la grille doit
    # faire exactement 100 — contrôle applicatif, car une contrainte SQL ne
    # peut pas porter sur l'ensemble des lignes d'une année.
    percentage: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    due_date: Mapped[date_type] = mapped_column(Date, nullable=False)

    academic_year: Mapped["AcademicYear"] = relationship()


class EnrollmentInstallment(Base, TimestampMixin):
    """Une échéance d'un accord de paiement passé avec une famille.

    En montants fixes : l'accord porte sur des sommes précises annoncées aux
    parents, pas sur des parts qui bougeraient au prochain ajustement tarifaire.
    """

    __tablename__ = "enrollment_installments"
    __table_args__ = (
        UniqueConstraint(
            "enrollment_id", "position", name="uq_enrollment_installment_enrollment_position"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    enrollment_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("enrollments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    due_date: Mapped[date_type] = mapped_column(Date, nullable=False)

    enrollment: Mapped["Enrollment"] = relationship()
