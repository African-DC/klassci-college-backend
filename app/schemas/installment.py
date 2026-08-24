"""Schémas des tranches — grille d'année, échéancier négocié, état de retard."""

from datetime import date as date_type

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.installment import FeeInstallmentKind


class FeeInstallmentInput(BaseModel):
    """Une tranche de la grille standard, en pourcentage ou en montant ferme.

    `kind` vaut `percentage` par défaut : un appel qui n'envoie qu'un
    pourcentage, comme le faisaient toutes les intégrations existantes,
    continue de décrire exactement la même tranche.
    """

    name: str = Field(..., min_length=1, max_length=100)
    position: int = Field(..., ge=1, le=24)
    kind: FeeInstallmentKind = FeeInstallmentKind.PERCENTAGE
    percentage: float | None = Field(default=None, gt=0, le=100)
    amount: float | None = Field(default=None, gt=0)
    due_date: date_type

    @field_validator("name")
    @classmethod
    def _trim(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Le nom de la tranche est requis")
        return cleaned

    @model_validator(mode="after")
    def _one_writing_only(self) -> "FeeInstallmentInput":
        """Une tranche porte un pourcentage ou un montant, jamais les deux.

        Accepter les deux obligerait le calcul à en choisir un en silence, et
        l'école lirait sur l'écran un chiffre qu'elle n'a pas saisi.
        """
        if self.kind is FeeInstallmentKind.PERCENTAGE:
            if self.percentage is None:
                raise ValueError("Une tranche en pourcentage a besoin d'un pourcentage")
            if self.amount is not None:
                raise ValueError("Une tranche en pourcentage ne porte pas de montant")
        else:
            if self.amount is None:
                raise ValueError("Une tranche en montant ferme a besoin d'un montant")
            if self.percentage is not None:
                raise ValueError("Une tranche en montant ferme ne porte pas de pourcentage")
        return self


class FeeInstallmentGridUpdate(BaseModel):
    """Grille complète d'une année. Remplacement intégral, jamais partiel."""

    installments: list[FeeInstallmentInput] = Field(..., min_length=1, max_length=24)


class FeeInstallmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    academic_year_id: int
    name: str
    position: int
    kind: str
    percentage: float | None = None
    amount: float | None = None
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
    # Part des frais obligatoires que la grille ne planifie pas. Vaut 0 sur une
    # grille en pourcentages, qui couvre tout par construction. Une grille en
    # montants fermes peut en laisser, puisque le total varie avec le niveau :
    # on l'annonce plutôt que de laisser l'écran afficher des échéances dont la
    # somme ne retombe pas sur le total dû, sans explication. Quand aucune
    # tranche n'est configurée, rien n'est planifié : ce champ vaut alors la
    # totalité des frais obligatoires, et personne n'est pour autant en retard.
    unscheduled_amount: float = 0.0
    lines: list[ScheduleLine] = Field(default_factory=list)
