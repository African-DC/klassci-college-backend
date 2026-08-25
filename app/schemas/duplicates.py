"""Ce que l'écran reçoit quand une fiche ressemble à une autre."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class InscriptionExistante(BaseModel):
    """Le dossier déjà ouvert pour l'année visée, validé ou non."""

    enrollment_id: int
    status: str
    class_name: str | None = None


class CorrespondanceResponse(BaseModel):
    student_id: int
    last_name: str
    first_name: str
    enrollment_number: str | None = None
    birth_date: date | None = None
    birth_place: str | None = None
    motif: str = Field(description="« matricule » (certain) ou « ressemblance »")
    score: float | None = Field(
        default=None, description="0 à 1. Absent quand le matricule suffit à conclure."
    )
    champs_compares: list[str] = Field(default_factory=list)
    juge_sur_peu: bool = Field(
        default=False,
        description=(
            "Vrai quand ni la date ni le lieu de naissance n'étaient disponibles : "
            "le score ne porte alors que sur le nom et le prénom, et l'écran doit "
            "le dire plutôt que d'afficher un pourcentage rassurant."
        ),
    )
    bloquant: bool = False
    inscription_annee_courante: InscriptionExistante | None = None


class DoublonsResponse(BaseModel):
    correspondances: list[CorrespondanceResponse] = Field(default_factory=list)
    total: int = 0
