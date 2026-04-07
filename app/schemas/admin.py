"""Schémas Pydantic pour le CRUD admin des entités de base."""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, field_validator


# ---------------------------------------------------------------------------
# Student
# ---------------------------------------------------------------------------


class StudentCreate(BaseModel):
    first_name: str
    last_name: str
    birth_date: date | None = None
    genre: str | None = None
    enrollment_number: str | None = None
    user_id: int | None = None

    @field_validator("genre")
    @classmethod
    def valid_genre(cls, v: str | None) -> str | None:
        if v is not None and v not in {"M", "F"}:
            raise ValueError("genre must be 'M' or 'F'")
        return v


class StudentUpdate(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    birth_date: date | None = None
    genre: str | None = None
    enrollment_number: str | None = None
    user_id: int | None = None

    @field_validator("genre")
    @classmethod
    def valid_genre(cls, v: str | None) -> str | None:
        if v is not None and v not in {"M", "F"}:
            raise ValueError("genre must be 'M' or 'F'")
        return v


class StudentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    first_name: str
    last_name: str
    birth_date: date | None
    genre: str | None
    enrollment_number: str | None
    user_id: int | None
    created_at: datetime
    updated_at: datetime


class StudentListResponse(BaseModel):
    items: list[StudentResponse]
    total: int
    page: int
    size: int


# ---------------------------------------------------------------------------
# TeacherProfile
# ---------------------------------------------------------------------------


class TeacherCreate(BaseModel):
    first_name: str
    last_name: str
    speciality: str | None = None
    phone: str | None = None
    user_id: int


class TeacherUpdate(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    speciality: str | None = None
    phone: str | None = None


class TeacherResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    first_name: str
    last_name: str
    speciality: str | None
    phone: str | None
    created_at: datetime
    updated_at: datetime


class TeacherListResponse(BaseModel):
    items: list[TeacherResponse]
    total: int
    page: int
    size: int


# ---------------------------------------------------------------------------
# StaffProfile
# ---------------------------------------------------------------------------


class StaffCreate(BaseModel):
    first_name: str
    last_name: str
    position: str | None = None
    phone: str | None = None
    user_id: int


class StaffUpdate(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    position: str | None = None
    phone: str | None = None


class StaffResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    first_name: str
    last_name: str
    position: str | None
    phone: str | None
    created_at: datetime
    updated_at: datetime


class StaffListResponse(BaseModel):
    items: list[StaffResponse]
    total: int
    page: int
    size: int


# ---------------------------------------------------------------------------
# Class
# ---------------------------------------------------------------------------


class ClassCreate(BaseModel):
    name: str
    level_id: int
    series_id: int | None = None
    academic_year_id: int
    room_id: int | None = None
    max_students: int = 40

    @field_validator("max_students")
    @classmethod
    def positive_max(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("max_students must be positive")
        return v


class ClassUpdate(BaseModel):
    name: str | None = None
    level_id: int | None = None
    series_id: int | None = None
    academic_year_id: int | None = None
    room_id: int | None = None
    max_students: int | None = None

    @field_validator("max_students")
    @classmethod
    def positive_max(cls, v: int | None) -> int | None:
        if v is not None and v <= 0:
            raise ValueError("max_students must be positive")
        return v


class ClassResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    level_id: int
    series_id: int | None
    academic_year_id: int
    room_id: int | None
    max_students: int
    created_at: datetime
    updated_at: datetime


class ClassListResponse(BaseModel):
    items: list[ClassResponse]
    total: int
    page: int
    size: int


# ---------------------------------------------------------------------------
# Subject
# ---------------------------------------------------------------------------


class SubjectCreate(BaseModel):
    name: str
    level_id: int | None = None
    series_id: int | None = None
    coefficient: int = 1
    hours_per_week: int = 2

    @field_validator("coefficient", "hours_per_week")
    @classmethod
    def positive_value(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("must be positive")
        return v


class SubjectUpdate(BaseModel):
    name: str | None = None
    level_id: int | None = None
    series_id: int | None = None
    coefficient: int | None = None
    hours_per_week: int | None = None

    @field_validator("coefficient", "hours_per_week")
    @classmethod
    def positive_value(cls, v: int | None) -> int | None:
        if v is not None and v <= 0:
            raise ValueError("must be positive")
        return v


class SubjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    level_id: int | None
    series_id: int | None
    coefficient: int
    hours_per_week: int
    created_at: datetime
    updated_at: datetime


class SubjectListResponse(BaseModel):
    items: list[SubjectResponse]
    total: int
    page: int
    size: int


# ---------------------------------------------------------------------------
# AcademicYear
# ---------------------------------------------------------------------------


class AcademicYearCreate(BaseModel):
    name: str
    start_date: date
    end_date: date
    is_current: bool = False

    @field_validator("end_date")
    @classmethod
    def end_after_start(cls, v: date, info: object) -> date:
        # info.data contains already-validated fields
        data = getattr(info, "data", {})
        start = data.get("start_date")
        if start and v <= start:
            raise ValueError("end_date must be after start_date")
        return v


class AcademicYearUpdate(BaseModel):
    name: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    is_current: bool | None = None


class AcademicYearResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    start_date: date
    end_date: date
    is_current: bool
    created_at: datetime
    updated_at: datetime


class AcademicYearListResponse(BaseModel):
    items: list[AcademicYearResponse]
    total: int
    page: int
    size: int


# ---------------------------------------------------------------------------
# Level
# ---------------------------------------------------------------------------


class LevelCreate(BaseModel):
    name: str
    order: int = 0


class LevelUpdate(BaseModel):
    name: str | None = None
    order: int | None = None


class LevelResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    order: int


class LevelListResponse(BaseModel):
    items: list[LevelResponse]
    total: int
    page: int
    size: int


# ---------------------------------------------------------------------------
# Enrollment Number Pattern
# ---------------------------------------------------------------------------


class EnrollmentPatternUpdate(BaseModel):
    pattern: str
    reset_counter: bool = False


class EnrollmentPatternPreview(BaseModel):
    pattern: str
    preview: str
    next_sequence: int
