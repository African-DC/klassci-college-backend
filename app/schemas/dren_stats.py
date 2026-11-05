"""Schémas Pydantic pour les statistiques DREN."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, computed_field


class _GenderBreakdown(BaseModel):
    """Effectif ventilé par sexe, avec la part que la fiche élève ne renseigne pas.

    `unspecified_count` est calculé, jamais stocké : il ne peut pas diverger de
    l'effectif. Sans lui, un élève sans sexe renseigné compte dans le total
    mais dans aucune colonne, et le document semble faux.
    """

    total_students: int
    male_count: int
    female_count: int

    @computed_field  # type: ignore[prop-decorator]
    @property
    def unspecified_count(self) -> int:
        return max(self.total_students - self.male_count - self.female_count, 0)


class ClassStats(_GenderBreakdown):
    """Statistiques d'une classe."""

    class_id: int
    class_name: str
    average: Decimal | None = None

    model_config = ConfigDict(from_attributes=True)


class LevelStats(_GenderBreakdown):
    """Statistiques d'un niveau scolaire."""

    level_id: int
    level_name: str
    success_rate: float | None = None
    classes: list[ClassStats]

    model_config = ConfigDict(from_attributes=True)


class SubjectStats(BaseModel):
    """Statistiques d'une matière."""

    subject_id: int
    subject_name: str
    overall_average: Decimal | None = None
    teacher_count: int

    model_config = ConfigDict(from_attributes=True)


class DrenStatsResponse(_GenderBreakdown):
    """Réponse complète des statistiques DREN pour une année scolaire."""

    academic_year_id: int
    academic_year_name: str
    success_rate: float | None = None
    failure_rate: float | None = None
    redoublement_rate: float | None = None
    exclusion_rate: float | None = None
    levels: list[LevelStats]
    subjects: list[SubjectStats]

    model_config = ConfigDict(from_attributes=True)


class DrenExportResponse(BaseModel):
    """Réponse d'export DREN (placeholder)."""

    export_url: str | None = None
    data: DrenStatsResponse
