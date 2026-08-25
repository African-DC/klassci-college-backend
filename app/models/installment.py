"""Tranches de paiement — grille standard de l'année et échéancier négocié.

Une tranche n'est **pas** une catégorie de frais. Le découpage « Scolarité
Trimestre 1/2/3 » confondait les deux : le trimestre est un moment de
paiement, pas une nature de frais. Ici, les catégories restent des natures
(Inscription, Scolarité, COGES, Tenue, et ce que l'école ajoute) et les
tranches découpent le **total obligatoire** dans le temps.

Deux niveaux :

- `FeeInstallment` — la grille de l'établissement pour une année scolaire.
  Chaque ligne s'exprime **au choix** en pourcentage ou en montant ferme, et
  une même grille mélange les deux : l'école pose en francs ce qu'elle sait
  déjà (« Inscription 37 000 F, payable à la rentrée ») et laisse les
  pourcentages absorber ce qui varie d'un niveau à l'autre. Un pourcentage
  porte sur ce qui reste **après** les montants fermes, jamais sur le total.
- `EnrollmentInstallment` — l'échéancier **négocié** avec une famille, en
  montants fixes cette fois, puisqu'il résulte d'un accord précis.

Ni l'un ni l'autre ne touche à l'allocation d'un versement : celle-ci reste
gouvernée par la priorité des catégories. Les tranches ne servent qu'à dire
ce qui est dû à quelle date, donc à calculer un retard honnête.
"""

import enum
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
from app.models.base import TimestampMixin, ValueEnum

if TYPE_CHECKING:
    from app.models.academic import AcademicYear
    from app.models.enrollment import Enrollment


class FeeInstallmentKind(str, enum.Enum):
    """Les deux façons d'exprimer une tranche.

    `PERCENTAGE` — une part de l'assiette, qui suit toute seule une 6e et une
    Terminale n'ayant pas les mêmes frais.
    `FIXED` — une somme en francs, annoncée telle quelle dans la brochure
    (« Inscription : 37 000 F »), identique pour tous les élèves de l'année.
    """

    PERCENTAGE = "percentage"
    FIXED = "fixed"


class FeeInstallment(Base, TimestampMixin):
    """Une tranche de la grille standard, en pourcentage ou en montant ferme."""

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
    # `percentage` par défaut : c'est ainsi que toutes les grilles existantes
    # ont été saisies, et le défaut serveur les laisse intactes.
    kind: Mapped[str] = mapped_column(
        ValueEnum(FeeInstallmentKind, name="fee_installment_kind"),
        nullable=False,
        default=FeeInstallmentKind.PERCENTAGE,
        server_default=FeeInstallmentKind.PERCENTAGE.value,
    )
    # Renseigné pour les tranches en pourcentage seulement. Part de l'assiette
    # **restante** après les montants fermes, pas du total : la somme des
    # pourcentages doit faire exactement 100 — contrôle applicatif, car une
    # contrainte SQL ne peut pas porter sur l'ensemble des lignes d'une année.
    percentage: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    # Renseigné pour les tranches en montant ferme seulement.
    amount: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
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
