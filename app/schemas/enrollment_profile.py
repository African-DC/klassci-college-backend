"""Schémas de la fiche de renseignements portée par l'inscription.

Les champs vivent ici une fois, et `EnrollmentCreate`, `EnrollmentWithStudentCreate`
et `ReEnrollmentCreate` en héritent : trois portes de création, une seule
définition de ce qu'elles acceptent.
"""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.deep_report import ScholarshipKind
from app.models.enrollment import ArtisticDiscipline, PreviousLevel, SecondLanguage

#: Les champs que PATCH /profile et le lot acceptent, dans cet ordre.
PROFILE_FIELDS = (
    "previous_level",
    "previous_series",
    "is_repeater",
    "lv2",
    "artistic_discipline",
)

#: Taille maximale d'un lot : une classe entière tient dedans.
BATCH_MAX_ITEMS = 100


class EnrollmentProfileFields(BaseModel):
    """Les colonnes de la fiche. `null` = pas renseigné, jamais deviné."""

    previous_level: PreviousLevel | None = None
    previous_series: str | None = Field(default=None, max_length=20)
    #: Qualité : `true` redoublant, `false` non redoublant.
    is_repeater: bool | None = None
    lv2: SecondLanguage | None = None
    artistic_discipline: ArtisticDiscipline | None = None

    @field_validator("previous_series")
    @classmethod
    def _strip_series(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return v.strip() or None


class EnrollmentProfileUpdate(EnrollmentProfileFields):
    """Corps de PATCH /enrollments/{id}/profile.

    Un champ absent reste intact ; un champ envoyé à `null` est effacé. Le
    service lit `model_fields_set` pour faire la différence.
    """


class EnrollmentProfileBatchItem(EnrollmentProfileUpdate):
    enrollment_id: int

    @field_validator("enrollment_id")
    @classmethod
    def _positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("must be a positive integer")
        return v


class EnrollmentProfileBatchRequest(BaseModel):
    """Un lot d'au plus cent fiches, appliqué en entier ou pas du tout."""

    items: list[EnrollmentProfileBatchItem] = Field(..., min_length=1, max_length=BATCH_MAX_ITEMS)

    @model_validator(mode="after")
    def _unique_ids(self) -> "EnrollmentProfileBatchRequest":
        seen: set[int] = set()
        doubles: set[int] = set()
        for item in self.items:
            if item.enrollment_id in seen:
                doubles.add(item.enrollment_id)
            seen.add(item.enrollment_id)
        if doubles:
            raise ValueError(f"enrollment_id en double dans le lot : {sorted(doubles)}")
        return self


class EnrollmentProfileBatchResponse(BaseModel):
    updated: int


class ScholarshipUpsert(BaseModel):
    """Corps de PUT /enrollments/{id}/scholarship."""

    kind: ScholarshipKind
    provider: str | None = Field(default=None, max_length=200)
    decision_number: str | None = Field(default=None, max_length=50)
    amount: Decimal | None = Field(default=None, ge=0, max_digits=15, decimal_places=2)
    granted_on: date | None = None


class ScholarshipSummary(BaseModel):
    """La bourse telle que l'inscription la montre."""

    model_config = ConfigDict(from_attributes=True)

    kind: ScholarshipKind
    provider: str | None = None
    decision_number: str | None = None
