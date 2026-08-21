"""Schemas Pydantic pour le CRUD des frais scolaires (FeeCategory, FeeVariant)."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.fee import FeeAssignmentScope

# ---------------------------------------------------------------------------
# FeeCategory
# ---------------------------------------------------------------------------


class FeeCategoryCreate(BaseModel):
    name: str
    description: str | None = None
    is_mandatory: bool = True
    # Ordre d'imputation des versements : plus petit = servi en premier.
    # Sans ce champ, toute categorie creee tombait a 100, donc derniere, et
    # rien ne permettait de la remonter depuis l'interface.
    priority: int = Field(default=100, ge=0, le=999)


class FeeCategoryUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    is_mandatory: bool | None = None
    priority: int | None = Field(default=None, ge=0, le=999)


class FeeCategoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    is_mandatory: bool
    priority: int
    created_at: datetime
    updated_at: datetime


class FeeCategoryListResponse(BaseModel):
    items: list[FeeCategoryResponse]
    total: int
    page: int
    size: int


# ---------------------------------------------------------------------------
# FeeVariant
# ---------------------------------------------------------------------------


class FeeVariantCreate(BaseModel):
    fee_category_id: int
    level_id: int
    series_id: int | None = None
    academic_year_id: int
    amount: Decimal
    description: str | None = None

    @field_validator("amount")
    @classmethod
    def positive_amount(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("amount must be positive")
        return v

    # `None` = ce tarif s'applique a tout le monde. Sinon il ne vaut que
    # pour les affectes ou que pour les non affectes.
    assignment_scope: FeeAssignmentScope | None = None


class FeeVariantUpdate(BaseModel):
    amount: Decimal | None = None
    description: str | None = None

    @field_validator("amount")
    @classmethod
    def positive_amount(cls, v: Decimal | None) -> Decimal | None:
        if v is not None and v <= 0:
            raise ValueError("amount must be positive")
        return v

    # `None` = ce tarif s'applique a tout le monde. Sinon il ne vaut que
    # pour les affectes ou que pour les non affectes. Remettre ce champ a
    # `None` doit rendre le tarif universel : le service distingue donc un
    # champ absent d'un champ envoye vide, sans quoi une portee posee par
    # erreur ne se retirerait plus jamais depuis l'ecran.
    assignment_scope: FeeAssignmentScope | None = None


class FeeVariantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    fee_category_id: int
    level_id: int
    series_id: int | None
    academic_year_id: int
    amount: Decimal
    description: str | None
    created_at: datetime
    updated_at: datetime
    assignment_scope: str | None = None


class FeeVariantListResponse(BaseModel):
    items: list[FeeVariantResponse]
    total: int
    page: int
    size: int


# ---------------------------------------------------------------------------
# Repercussion d'un tarif modifie sur les inscriptions existantes
# ---------------------------------------------------------------------------


class _FeePropagationImpact(BaseModel):
    """Le socle chiffre commun a l'apercu et au resultat.

    Les deux reponses portent les memes compteurs, sous les memes noms : c'est
    ce qui permet a l'ecole de comparer ce qu'on lui avait annonce et ce qui a
    ete fait.
    """

    variant_id: int
    fee_category_id: int
    category_name: str
    academic_year_id: int
    #: Le montant du tarif tel qu'il est aujourd'hui : celui qui sera recopie.
    amount: Decimal
    #: Somme des quatre paquets. Une categorie ne produisant qu'une ligne par
    #: inscription, ce total est aussi le nombre d'inscriptions touchees.
    enrollments_concerned: int
    fees_already_up_to_date: int
    fees_kept_with_payments: int
    fees_waived: int
    #: Ecart total de dette en francs, negatif quand le tarif baisse.
    debt_delta: Decimal
    message: str


class FeePropagationPreview(_FeePropagationImpact):
    """Ce qui se passerait. Rien n'est ecrit."""

    fees_to_update: int


class FeePropagationResult(_FeePropagationImpact):
    """Ce qui a ete ecrit : le compte des lignes reellement reecrites."""

    fees_updated: int


# ---------------------------------------------------------------------------
# OptionalFeeOption
# ---------------------------------------------------------------------------


class OptionalFeeOptionCreate(BaseModel):
    fee_category_id: int
    academic_year_id: int
    name: str
    amount: Decimal
    description: str | None = None

    @field_validator("amount")
    @classmethod
    def positive_amount(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("amount must be positive")
        return v


class OptionalFeeOptionUpdate(BaseModel):
    name: str | None = None
    amount: Decimal | None = None
    description: str | None = None

    @field_validator("amount")
    @classmethod
    def positive_amount(cls, v: Decimal | None) -> Decimal | None:
        if v is not None and v <= 0:
            raise ValueError("amount must be positive")
        return v


class OptionalFeeOptionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    fee_category_id: int
    academic_year_id: int
    name: str
    amount: Decimal
    description: str | None
    created_at: datetime
    updated_at: datetime


class OptionalFeeOptionListResponse(BaseModel):
    items: list[OptionalFeeOptionResponse]
    total: int
    page: int
    size: int
