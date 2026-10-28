"""Schémas des enseignants rattachés à une matière."""

from pydantic import BaseModel


class SubjectTeacherRef(BaseModel):
    id: int
    full_name: str


class SubjectSlotCount(BaseModel):
    teacher_id: int
    slots: int


class SubjectSlotCountsResponse(BaseModel):
    counts: list[SubjectSlotCount]
