"""Schémas Pydantic pour les inscriptions."""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.fee import FeeEntitlement


class EnrollmentCreate(BaseModel):
    student_id: int
    class_id: int
    academic_year_id: int
    fee_variant_id: int | None = None
    notes: str | None = None

    @field_validator("academic_year_id", "student_id", "class_id")
    @classmethod
    def must_be_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("must be a positive integer")
        return v

    assignment_status: str | None = None
    assignment_decision_number: str | None = None


class EnrollmentUpdate(BaseModel):
    status: str | None = None
    notes: str | None = None
    class_id: int | None = None

    @field_validator("status")
    @classmethod
    def valid_status(cls, v: str | None) -> str | None:
        if v is None:
            return v
        allowed = {"prospect", "en_validation", "valide", "rejete", "annule"}
        if v not in allowed:
            raise ValueError(f"status must be one of {sorted(allowed)}")
        return v

    @field_validator("class_id")
    @classmethod
    def positive_class_id(cls, v: int | None) -> int | None:
        if v is not None and v <= 0:
            raise ValueError("class_id must be a positive integer")
        return v

    assignment_status: str | None = None
    assignment_decision_number: str | None = None


class SubscribeOptionRequest(BaseModel):
    optional_fee_option_id: int

    @field_validator("optional_fee_option_id")
    @classmethod
    def positive_option_id(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("optional_fee_option_id must be a positive integer")
        return v


class EnrollmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    student_id: int
    class_id: int
    academic_year_id: int
    academic_year_name: str
    status: str
    fee_variant_id: int | None
    notes: str | None
    created_by: int | None
    created_at: datetime
    updated_at: datetime
    student_first_name: str | None = None
    student_last_name: str | None = None
    class_name: str | None = None
    assignment_status: str | None = None
    assignment_decision_number: str | None = None


class EnrollmentListResponse(BaseModel):
    items: list[EnrollmentResponse]
    total: int
    page: int
    size: int


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    enrollment_id: int
    type: str
    file_url: str
    original_name: str | None
    created_at: datetime


# ---------------------------------------------------------------------------
# Composite enrollment (student + parent + enrollment in one call)
# ---------------------------------------------------------------------------


class ParentInput(BaseModel):
    first_name: str
    last_name: str
    phone: str | None = None
    email: str | None = None
    city: str | None = None
    commune: str | None = None
    password: str | None = None  # If email+password provided, creates a User account
    relationship_type: str = "guardian"

    @field_validator("relationship_type")
    @classmethod
    def valid_relationship(cls, v: str) -> str:
        allowed = {"father", "mother", "guardian", "other"}
        if v not in allowed:
            raise ValueError(f"relationship_type must be one of {sorted(allowed)}")
        return v


class EnrollmentWithStudentCreate(BaseModel):
    """Creates a Student + optional Parent + Enrollment in one transaction."""

    # Student info
    first_name: str
    last_name: str
    birth_date: date | None = None
    genre: str | None = None
    enrollment_number: str | None = None
    city: str | None = None
    commune: str | None = None
    # Optional parent
    parent: ParentInput | None = None
    # Enrollment info
    class_id: int
    academic_year_id: int | None = None  # if None, use current year
    # Statut d'affectation : il decide du tarif applique, il doit donc
    # etre saisi au moment ou l'inscription est creee.
    assignment_status: str | None = None
    assignment_decision_number: str | None = None
    fee_variant_id: int | None = None
    notes: str | None = None

    @field_validator("genre")
    @classmethod
    def valid_genre(cls, v: str | None) -> str | None:
        if v is not None and v not in {"M", "F"}:
            raise ValueError("genre must be 'M' or 'F'")
        return v

    @field_validator("class_id")
    @classmethod
    def positive_class_id(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("must be a positive integer")
        return v


class ReEnrollmentCreate(BaseModel):
    """Re-enrolls an existing student for a new year/class."""

    student_id: int
    class_id: int
    academic_year_id: int | None = None  # if None, use current year
    fee_variant_id: int | None = None
    notes: str | None = None

    @field_validator("student_id", "class_id")
    @classmethod
    def must_be_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("must be a positive integer")
        return v


# ---------------------------------------------------------------------------
# Fee variant resolution
# ---------------------------------------------------------------------------


class FeeVariantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    fee_category_id: int
    category_name: str
    #: Ce que ce frais ouvre a la famille. Repris de la categorie : sans lui,
    #: l'ecran affiche un montant sans jamais dire ce qu'il achete.
    entitlements: list[FeeEntitlement] = Field(default_factory=list)
    is_mandatory: bool = True
    level_id: int | None
    series_id: int | None
    academic_year_id: int
    amount: Decimal
    description: str | None
