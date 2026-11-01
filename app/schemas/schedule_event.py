"""Contracts for recurring school-wide and class-specific schedule events."""

from datetime import time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.timetable import DayOfWeek

EventCategory = Literal["recess", "lunch", "interclass", "study", "assembly", "other"]


class ScheduleEventCreate(BaseModel):
    academic_year_id: int = Field(gt=0)
    class_id: int | None = Field(default=None, gt=0)
    title: str = Field(min_length=1, max_length=100)
    category: EventCategory
    blocks_courses: bool = True
    day: DayOfWeek
    start_time: time
    end_time: time

    @field_validator("title")
    @classmethod
    def non_empty_title(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Le libellé ne peut pas être vide.")
        return cleaned

    @model_validator(mode="after")
    def valid_range(self):
        if any((t.second, t.microsecond) != (0, 0) for t in (self.start_time, self.end_time)):
            raise ValueError("Utilisez des horaires précis à la minute, sans secondes.")
        if self.start_time >= self.end_time:
            raise ValueError("La fin doit être après le début.")
        return self


class ScheduleEventResponse(ScheduleEventCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
