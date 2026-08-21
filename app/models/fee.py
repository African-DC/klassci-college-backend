"""Modèles de frais scolaires : FeeCategory, FeeVariant, OptionalFeeOption, EnrollmentFee, Payment."""

from __future__ import annotations

import enum
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    Computed,
    ForeignKey,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, ValueEnum

if TYPE_CHECKING:
    from app.models.academic import AcademicYear, Level, Series
    from app.models.enrollment import Enrollment, StudentOption


class PaymentMethod(str, enum.Enum):
    CASH = "cash"
    MOBILE_MONEY = "mobile_money"
    BANK_TRANSFER = "bank_transfer"
    CHEQUE = "cheque"


class PaymentStatus(str, enum.Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    REFUNDED = "refunded"
    CANCELLED = "cancelled"


class EnrollmentFeeStatus(str, enum.Enum):
    PENDING = "pending"
    PARTIAL = "partial"
    PAID = "paid"
    WAIVED = "waived"


# ---------------------------------------------------------------------------
# FeeCategory
# ---------------------------------------------------------------------------


class FeeAssignmentScope(str, enum.Enum):
    """A qui s'applique un tarif selon l'affectation.

    Deux cas seulement la ou l'inscription en connait trois : un reaffecte
    est subventionne comme un affecte, lui reserver une troisieme colonne
    reviendrait a la laisser vide en doublant la saisie.

    `None` sur un tarif signifie « s'applique a tout le monde » : c'est ce
    qui permet aux grilles deja configurees de continuer a fonctionner sans
    qu'on y touche.
    """

    AFFECTE = "affecte"
    NON_AFFECTE = "non_affecte"


class FeeCategory(Base, TimestampMixin):
    """Catégorie de frais (ex : Inscription, Scolarité T1, Cantine, Transport).

    is_mandatory=True  → frais obligatoires, montants via FeeVariant (par level+series)
    is_mandatory=False → frais optionnels, options nommées via OptionalFeeOption
    """

    __tablename__ = "fee_categories"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_mandatory: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Ordre d'allocation des paiements automatiques. Lower = paid first.
    # Convention : 10 Inscription, 20/30/40 T1/T2/T3, 50 COGES, 60 Tenue, 100 reste.
    priority: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=100, server_default="100"
    )

    variants: Mapped[list[FeeVariant]] = relationship(
        back_populates="category",
        # `passive_deletes` laisse la base parler : sans lui, SQLAlchemy
        # tente de detacher les enfants en mettant leur cle a NULL avant le
        # DELETE. Sur une colonne NOT NULL ca produit une erreur illisible,
        # et sur une colonne nullable ca reussit — en vidant silencieusement
        # la reference, ce qui est pire.
        passive_deletes=True,
    )
    options: Mapped[list[OptionalFeeOption]] = relationship(
        back_populates="category", passive_deletes=True
    )


# ---------------------------------------------------------------------------
# FeeVariant — montant applicable à une classe / année
# ---------------------------------------------------------------------------


class FeeVariant(Base, TimestampMixin):
    """Montant d'un frais OBLIGATOIRE pour un level + series + année scolaire."""

    __tablename__ = "fee_variants"
    __table_args__ = (
        UniqueConstraint(
            "fee_category_id",
            "academic_year_id",
            "level_key",
            "series_key",
            "scope_key",
            name="uq_fee_variant_dimensions",
        ),
    )

    # Colonnes generees par la base : `NULL` n'etant jamais egal a `NULL`,
    # une contrainte posee directement sur `level_id` / `series_id` /
    # `assignment_scope` ne se declenche jamais des que l'un d'eux est vide.
    # C'est ce qui laissait creer des tarifs en double sur tous les niveaux de
    # college, ou la serie est toujours vide.
    level_key: Mapped[int] = mapped_column(
        BigInteger, Computed("COALESCE(level_id, 0)", persisted=True), nullable=False
    )
    series_key: Mapped[int] = mapped_column(
        BigInteger, Computed("COALESCE(series_id, 0)", persisted=True), nullable=False
    )
    scope_key: Mapped[str] = mapped_column(
        String(20), Computed("COALESCE(assignment_scope, '')", persisted=True), nullable=False
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    fee_category_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("fee_categories.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    academic_year_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("academic_years.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    level_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("levels.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    assignment_scope: Mapped[str | None] = mapped_column(
        ValueEnum(FeeAssignmentScope, name="fee_assignment_scope"),
        nullable=True,
        index=True,
    )
    series_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("series.id", ondelete="RESTRICT"), nullable=True, index=True
    )

    category: Mapped[FeeCategory] = relationship(back_populates="variants")
    academic_year: Mapped[AcademicYear] = relationship()
    level: Mapped[Level | None] = relationship()
    series: Mapped[Series | None] = relationship()
    enrollment_fees: Mapped[list[EnrollmentFee]] = relationship(
        back_populates="fee_variant", passive_deletes=True
    )


# ---------------------------------------------------------------------------
# OptionalFeeOption — frais optionnels (ex : transport, cantine)
# ---------------------------------------------------------------------------


class OptionalFeeOption(Base, TimestampMixin):
    """Option nommée d'un frais OPTIONNEL (ex: Menu complet, Arrêt Koumassi)."""

    __tablename__ = "optional_fee_options"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    fee_category_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("fee_categories.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    academic_year_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("academic_years.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    category: Mapped[FeeCategory] = relationship(back_populates="options")
    academic_year: Mapped[AcademicYear] = relationship()
    student_options: Mapped[list[StudentOption]] = relationship(
        back_populates="optional_fee_option", passive_deletes=True
    )


# ---------------------------------------------------------------------------
# EnrollmentFee — frais dûs par une inscription
# ---------------------------------------------------------------------------


class EnrollmentFee(Base, TimestampMixin):
    """Frais applicable à une inscription spécifique.

    Une catégorie de frais ne produit qu'une seule ligne : la Scolarité T1 est
    due une fois, quel que soit le nombre de tarifs que l'école a saisis pour
    elle. La règle vivait dans une fonction Python, et il existe deux chemins
    d'insertion ; elle vit désormais dans la base, portée par
    `uq_enrollment_fee_category`.
    """

    __tablename__ = "enrollment_fees"
    __table_args__ = (
        UniqueConstraint("enrollment_id", "fee_category_id", name="uq_enrollment_fee_category"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    enrollment_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("enrollments.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    fee_variant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("fee_variants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    #: Recopiée du tarif : MySQL n'accepte pas de colonne générée ici, une
    #: expression STORED ne pouvant lire que les colonnes de sa propre ligne.
    #: Renseignée par les deux chemins d'écriture, et NOT NULL pour qu'un
    #: troisième chemin qui l'oublierait échoue au lieu de recréer le doublon.
    fee_category_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("fee_categories.id", ondelete="RESTRICT"), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    status: Mapped[str] = mapped_column(
        ValueEnum(EnrollmentFeeStatus, name="enrollment_fee_status"),
        nullable=False,
        default=EnrollmentFeeStatus.PENDING,
        index=True,
    )

    enrollment: Mapped[Enrollment] = relationship(back_populates="enrollment_fees")
    fee_variant: Mapped[FeeVariant] = relationship(back_populates="enrollment_fees")
    payments: Mapped[list[Payment]] = relationship(back_populates="enrollment_fee")


# ---------------------------------------------------------------------------
# Payment
# ---------------------------------------------------------------------------


class Payment(Base, TimestampMixin):
    """Acte caissier — un versement physique par un parent/élève.

    Modèle métier (Côte d'Ivoire) : le caissier saisit un montant sur
    l'INSCRIPTION de l'élève. Le système alloue automatiquement aux
    frais impayés par ordre de priorité (Inscription → T1 → T2 → T3 →
    COGES → Tenue → reste). Les splits sont matérialisés dans
    `PaymentAllocation` pour la traçabilité comptable.

    `enrollment_fee_id` est DEPRECATED depuis le refactor 2026-05-17
    (migration 0028). Conservé nullable 1 release pour rollback. Tout
    nouveau code doit utiliser `enrollment_id` + parcourir `allocations`.

    **Un versement survit à l'élève.** Quand l'administration supprime
    définitivement une fiche élève, l'inscription et les frais partent, mais
    pas les versements : la caissière avait compté ces billets, le tiroir
    était juste ce soir-là, et tous les points journaliers déjà imprimés
    disent cette somme. Les effacer ferait mentir des documents signés.

    D'où `enrollment_id` nullable et les deux colonnes `*_snapshot` : le nom
    et le matricule sont recopiés sur le versement avant que la fiche ne
    parte, pour que le bordereau reste lisible une fois l'élève disparu.
    """

    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # Nullable : un versement orphelin est un versement dont l'élève a été
    # supprimé. Il garde son montant, sa date et son encaisseur — c'est ce
    # qui fait tenir les totaux de caisse.
    enrollment_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("enrollments.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    # Identité figée de l'élève, recopiée avant que sa fiche ne parte.
    # Renseignée dès la mise à la corbeille : le filtre qui masque les fiches
    # archivées masque aussi l'élève derrière le versement, et un bordereau
    # sans nom ne se relit pas.
    student_name_snapshot: Mapped[str | None] = mapped_column(String(200), nullable=True)
    student_matricule_snapshot: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # DEPRECATED — conservé pour rétrocompat. Ne plus écrire dessus.
    # TODO(remove-after=0.3.0): drop column + index once all environments
    # have run migration 0028 and no Payment row has enrollment_fee_id set.
    enrollment_fee_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("enrollment_fees.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    method: Mapped[str] = mapped_column(
        ValueEnum(PaymentMethod, name="payment_method"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        ValueEnum(PaymentStatus, name="payment_status"),
        nullable=False,
        default=PaymentStatus.PENDING,
        index=True,
    )
    reference: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    received_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    enrollment: Mapped[Enrollment | None] = relationship(back_populates="payments")
    enrollment_fee: Mapped[EnrollmentFee | None] = relationship(back_populates="payments")
    allocations: Mapped[list[PaymentAllocation]] = relationship(
        back_populates="payment",
        cascade="all, delete-orphan",
    )


# ---------------------------------------------------------------------------
# PaymentAllocation — splits d'un paiement vers les frais individuels
# ---------------------------------------------------------------------------


class PaymentAllocation(Base, TimestampMixin):
    """Split d'un Payment vers un EnrollmentFee spécifique.

    Un Payment de 50 000 XOF peut être alloué automatiquement à plusieurs
    frais (ex : 20 000 sur T1 + 10 000 sur T2 + 20 000 sur T3). Chaque
    split est une row PaymentAllocation. La somme des allocations.amount
    DOIT toujours égaler payment.amount (invariant comptable).
    """

    __tablename__ = "payment_allocations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    payment_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("payments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    enrollment_fee_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("enrollment_fees.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)

    payment: Mapped[Payment] = relationship(back_populates="allocations")
    enrollment_fee: Mapped[EnrollmentFee] = relationship()
