"""Schémas des actes de vie scolaire : convocations et autorisations de rattrapage."""

from datetime import date, datetime, time

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.school_life import SummonsOutcome

_VALID_OUTCOMES = {o.value for o in SummonsOutcome}


# ---------------------------------------------------------------------------
# Convocation de parent
# ---------------------------------------------------------------------------


class ParentSummonsCreate(BaseModel):
    student_id: int
    # L'un ou l'autre : la fiche du tuteur quand elle existe, sinon le nom
    # dicté au guichet. Un des deux est obligatoire, sinon la convocation
    # sortirait au nom de personne.
    parent_id: int | None = None
    parent_name: str | None = Field(None, max_length=200)
    summons_date: date
    summons_time: time
    reason: str = Field(min_length=3, max_length=2000)
    trimester: int | None = Field(None, ge=1, le=3)

    @field_validator("reason", "parent_name", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def _check(self) -> "ParentSummonsCreate":
        if self.parent_id is None and not (self.parent_name or "").strip():
            raise ValueError("Indiquez le tuteur convoqué : une fiche parent ou un nom.")
        # On convoque pour demain, jamais pour avant-hier : une convocation
        # antidatée ne sert qu'à couvrir une réunion qui a déjà eu lieu.
        if self.summons_date < date.today():
            raise ValueError("La date de convocation doit être aujourd'hui ou à venir.")
        return self


class SummonsOutcomeUpdate(BaseModel):
    outcome: str
    notes: str | None = Field(None, max_length=2000)

    @field_validator("outcome")
    @classmethod
    def _valid_outcome(cls, value: str) -> str:
        if value not in _VALID_OUTCOMES:
            raise ValueError(f"Suite invalide. Valeurs : {', '.join(sorted(_VALID_OUTCOMES))}")
        return value


class ParentSummonsResponse(BaseModel):
    id: int
    student_id: int
    student_name: str
    enrollment_number: str | None = None
    class_name: str | None = None
    parent_id: int | None = None
    parent_name: str | None = None
    academic_year_id: int
    academic_year_name: str | None = None
    trimester: int
    summons_date: date
    summons_time: time
    reason: str
    reference: str | None = None
    outcome: str
    outcome_label: str
    outcome_notes: str | None = None
    outcome_recorded_at: datetime | None = None
    issued_by_user_id: int
    issued_by_name: str | None = None
    created_at: datetime


class SummonsRegisterSummary(BaseModel):
    """Ce que le conseil de classe demande : combien convoqués, combien venus."""

    total: int
    attended: int
    missed: int
    pending: int


class ParentSummonsRegister(BaseModel):
    """Une page du registre, et le décompte de tout le registre consulté.

    `summary` ne décrit jamais `items` : il porte sur l'ensemble des lignes de
    l'année, du trimestre et de l'élève consultés, quelle que soit la page
    affichée et quelle que soit la suite filtrée. Un décompte calculé sur les
    lignes déjà filtrées répondait « Convocations 8, Tuteur absent 8 » dès
    qu'on cliquait « Tuteur absent » : l'éducateur croyait lire
    l'établissement, il lisait son propre filtre.
    """

    items: list[ParentSummonsResponse]
    summary: SummonsRegisterSummary
    total: int
    page: int
    size: int


# ---------------------------------------------------------------------------
# Autorisation de rattrapage (billet d'annulation de zéro)
# ---------------------------------------------------------------------------


class RetakeAuthorizationCreate(BaseModel):
    student_id: int
    period_start: date
    period_end: date
    reason: str = Field(min_length=3, max_length=2000)
    evaluation_ids: list[int] = Field(min_length=1)

    @field_validator("reason", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def _check_period(self) -> "RetakeAuthorizationCreate":
        if self.period_end < self.period_start:
            raise ValueError("La fin de la période doit suivre son début.")
        if len(set(self.evaluation_ids)) != len(self.evaluation_ids):
            raise ValueError("Une évaluation ne peut être visée qu'une seule fois.")
        return self


class RetakeTargetResponse(BaseModel):
    evaluation_id: int
    title: str
    subject_name: str | None = None
    date: date
    coefficient: int
    trimester: int


class RetakeAuthorizationResponse(BaseModel):
    id: int
    student_id: int
    student_name: str
    enrollment_number: str | None = None
    class_name: str | None = None
    academic_year_id: int
    academic_year_name: str | None = None
    trimester: int
    period_start: date
    period_end: date
    reason: str
    reference: str | None = None
    issued_by_user_id: int
    issued_by_name: str | None = None
    evaluations: list[RetakeTargetResponse]
    created_at: datetime


class RetakeAuthorizationList(BaseModel):
    items: list[RetakeAuthorizationResponse]
    total: int
    page: int
    size: int


# ---------------------------------------------------------------------------
# Billet d'entrée
# ---------------------------------------------------------------------------


class EntrySlipRequest(BaseModel):
    """Le billet ferme une absence déjà saisie et fixe la reprise des cours."""

    resume_date: date | None = None
    notes: str | None = Field(None, max_length=500)

    @field_validator("notes", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value
