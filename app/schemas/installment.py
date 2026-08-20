"""Schémas des tranches — grille d'année, échéancier négocié, état de retard."""

from datetime import date as date_type

from pydantic import BaseModel, ConfigDict, Field, field_validator


class FeeInstallmentInput(BaseModel):
    """Une tranche de la grille standard, en pourcentage du total obligatoire."""

    name: str = Field(..., min_length=1, max_length=100)
    position: int = Field(..., ge=1, le=24)
    percentage: float = Field(..., gt=0, le=100)
    due_date: date_type

    @field_validator("name")
    @classmethod
    def _trim(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Le nom de la tranche est requis")
        return cleaned


class FeeInstallmentGridUpdate(BaseModel):
    """Grille complète d'une année. Remplacement intégral, jamais partiel."""

    installments: list[FeeInstallmentInput] = Field(..., min_length=1, max_length=24)


class FeeInstallmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    academic_year_id: int
    name: str
    position: int
    percentage: float
    due_date: date_type


class EnrollmentInstallmentInput(BaseModel):
    """Une échéance d'un accord négocié, en montant ferme."""

    name: str = Field(..., min_length=1, max_length=100)
    position: int = Field(..., ge=1, le=24)
    amount: float = Field(..., gt=0)
    due_date: date_type

    @field_validator("name")
    @classmethod
    def _trim(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Le nom de l'échéance est requis")
        return cleaned


class EnrollmentPlanUpdate(BaseModel):
    installments: list[EnrollmentInstallmentInput] = Field(..., min_length=1, max_length=24)


class ScheduleLine(BaseModel):
    """Une échéance résolue, avec son état à la date du jour."""

    name: str
    position: int
    amount: float
    due_date: date_type
    # `true` dès que la date est atteinte, même si la tranche est payée.
    is_due: bool


class EnrollmentScheduleResponse(BaseModel):
    """Échéancier applicable à une inscription, et son état de retard.

    `source` vaut `negotiated` quand la famille a un accord propre, `standard`
    quand on applique la grille de l'année, et `none` quand l'établissement
    n'a pas encore configuré de tranches — auquel cas personne n'est en retard.
    """

    enrollment_id: int
    source: str
    total_mandatory: float
    total_paid: float
    due_so_far: float
    late_amount: float
    is_late: bool
    next_due_date: date_type | None = None
    next_due_amount: float | None = None
    lines: list[ScheduleLine] = Field(default_factory=list)
