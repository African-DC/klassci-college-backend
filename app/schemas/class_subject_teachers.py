"""Schémas de l'enseignant retenu par classe et par matière."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.subject_teachers import SubjectTeacherRef

MAX_ASSIGNMENTS = 60


class ClassSubjectTeacherItem(BaseModel):
    subject_id: int
    subject_name: str
    hours_per_week: int
    series_name: str | None
    eligible_teachers: list[SubjectTeacherRef]
    assigned_teacher_id: int | None
    resolved_teacher_id: int | None
    source: Literal["explicit", "single", "none"]


class ClassSubjectTeachersResponse(BaseModel):
    class_id: int
    class_name: str
    items: list[ClassSubjectTeacherItem]
    missing_count: int


class ClassSubjectTeacherAssignment(BaseModel):
    subject_id: int
    teacher_id: int | None = None


class ClassSubjectTeachersUpdate(BaseModel):
    assignments: list[ClassSubjectTeacherAssignment] = Field(max_length=MAX_ASSIGNMENTS)

    @field_validator("assignments")
    @classmethod
    def _une_seule_ligne_par_matiere(
        cls, valeur: list[ClassSubjectTeacherAssignment]
    ) -> list[ClassSubjectTeacherAssignment]:
        ids = [a.subject_id for a in valeur]
        if len(ids) != len(set(ids)):
            raise ValueError("Une matière ne peut figurer qu'une fois.")
        return valeur
