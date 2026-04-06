"""Schémas Pydantic pour les statistiques DREN."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class ClassStats(BaseModel):
    """Statistiques d'une classe."""

    class_id: int
    class_name: str
    total_students: int
    male_count: int
    female_count: int
    average: Decimal | None = None

    model_config = ConfigDict(from_attributes=True)


class LevelStats(BaseModel):
    """Statistiques d'un niveau scolaire."""

    level_id: int
    level_name: str
    total_students: int
    male_count: int
    female_count: int
    classes: list[ClassStats]

    model_config = ConfigDict(from_attributes=True)


class SubjectStats(BaseModel):
    """Statistiques d'une matière."""

    subject_id: int
    subject_name: str
    overall_average: Decimal | None = None
    teacher_count: int

    model_config = ConfigDict(from_attributes=True)


class DrenStatsResponse(BaseModel):
    """Réponse complète des statistiques DREN pour une année scolaire."""

    academic_year_id: int
    academic_year_name: str
    total_students: int
    male_count: int
    female_count: int
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
