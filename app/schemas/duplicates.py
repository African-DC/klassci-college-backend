"""Ce que l'écran reçoit quand une fiche ressemble à une autre."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class ExistingEnrollment(BaseModel):
    """Le dossier déjà ouvert pour l'année visée, validé ou non."""

    enrollment_id: int
    status: str
    class_name: str | None = None


class MatchResponse(BaseModel):
    student_id: int
    last_name: str
    first_name: str
    enrollment_number: str | None = None
    birth_date: date | None = None
    reason: Literal["enrollment_number", "similarity"] = Field(
        description="Certitude (matricule identique) ou ressemblance de l'état civil."
    )
    score: float | None = Field(
        default=None, description="0 à 1. Absent quand le matricule suffit à conclure."
    )
    partial_identity: bool = Field(
        default=False,
        description=(
            "Vrai quand un des champs d'état civil n'a pas pu être comparé : "
            "le score ne porte alors que sur une partie de l'identité, et "
            "l'écran doit le dire plutôt que d'afficher un pourcentage rassurant."
        ),
    )
    current_year_enrollment: ExistingEnrollment | None = None


class DuplicatesResponse(BaseModel):
    matches: list[MatchResponse] = Field(default_factory=list)
    truncated: bool = Field(
        default=False,
        description=(
            "Vrai quand le plafond de candidats a été atteint : le vrai doublon "
            "peut se trouver au-delà. Sans ce signal, « rien trouvé » passerait "
            "pour une certitude alors qu'on n'a pas tout regardé."
        ),
    )
