"""Schémas de la fiche de renseignements par classe (GET information-sheet)."""

from datetime import date

from pydantic import BaseModel

from app.models.deep_report import ScholarshipKind
from app.models.enrollment import ArtisticDiscipline, PreviousLevel, SecondLanguage


class InformationSheetYear(BaseModel):
    id: int
    name: str


class InformationSheetRow(BaseModel):
    """Une ligne de la fiche : un élève inscrit. `null` = pas renseigné."""

    enrollment_id: int
    matricule: str | None
    last_name: str
    first_name: str
    genre: str | None
    level_name: str
    birth_date: date | None
    birth_place: str | None
    nationality: str | None
    assignment_status: str | None
    scholarship_kind: ScholarshipKind | None
    is_repeater: bool | None
    lv2: SecondLanguage | None
    artistic_discipline: ArtisticDiscipline | None
    has_photo: bool
    previous_level: PreviousLevel | None
    previous_series: str | None


class InformationSheetClass(BaseModel):
    id: int
    name: str
    level_name: str
    rows: list[InformationSheetRow]


class InformationSheetResponse(BaseModel):
    academic_year: InformationSheetYear
    classes: list[InformationSheetClass]
