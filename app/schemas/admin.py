"""Schémas Pydantic pour le CRUD admin des entités de base."""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, field_validator


# ---------------------------------------------------------------------------
# Student
# ---------------------------------------------------------------------------


class StudentCreate(BaseModel):
    first_name: str
    last_name: str
    email: str
    password: str
    birth_date: date | None = None
    genre: str | None = None
    enrollment_number: str | None = None

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
    photo_url: str | None = None
    user_id: int | None
    created_at: datetime
    updated_at: datetime


class StudentFullResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    # Basic student info
    id: int
    first_name: str
    last_name: str
    birth_date: date | None
    genre: str | None
    enrollment_number: str | None
    photo_url: str | None = None
    user_id: int | None
    created_at: datetime
    updated_at: datetime

    # User account info (from User model)
    user_email: str | None = None
    user_is_active: bool | None = None
    user_last_login: datetime | None = None
    user_created_at: datetime | None = None

    # Current enrollment summary
    current_class_name: str | None = None
    current_academic_year: str | None = None
    current_enrollment_status: str | None = None
    current_enrollment_id: int | None = None

    # Aggregated KPIs
    attendance_total: int = 0
    attendance_present: int = 0
    attendance_absent: int = 0
    attendance_late: int = 0
    attendance_rate: float = 0.0

    # Financial summary
    fees_expected: float = 0.0
    fees_paid: float = 0.0
    fees_remaining: float = 0.0
    fees_rate: float = 0.0


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
    email: str
    password: str
    speciality: str | None = None
    phone: str | None = None


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


class TeacherFullResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    # Basic teacher info
    id: int
    user_id: int
    first_name: str
    last_name: str
    speciality: str | None
    phone: str | None
    created_at: datetime
    updated_at: datetime

    # User account info
    user_email: str | None = None
    user_is_active: bool | None = None
    user_last_login: datetime | None = None
    user_created_at: datetime | None = None

    # Aggregated KPIs
    classes_count: int = 0
    students_count: int = 0
    evaluations_count: int = 0


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


class StaffFullResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    # Basic staff info
    id: int
    user_id: int
    first_name: str
    last_name: str
    position: str | None
    phone: str | None
    created_at: datetime
    updated_at: datetime

    # User account info
    user_email: str | None = None
    user_is_active: bool | None = None
    user_last_login: datetime | None = None
    user_created_at: datetime | None = None


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


# ---------------------------------------------------------------------------
# School Settings
# ---------------------------------------------------------------------------


class SchoolSettingsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    school_name: str
    address: str | None
    phone: str | None
    email: str | None
    logo_url: str | None
    ministry_code: str | None
    enrollment_number_pattern: str | None
    enrollment_number_counter: int
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Student Enrollment Fees (for payment modal)
# ---------------------------------------------------------------------------


class UserAccountUpdate(BaseModel):
    email: str | None = None
    password: str | None = None

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str | None) -> str | None:
        if v is not None and "@" not in v:
            raise ValueError("Email invalide")
        return v

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str | None) -> str | None:
        if v is not None and len(v) < 8:
            raise ValueError("Le mot de passe doit contenir au moins 8 caractères")
        return v


class StudentEnrollmentFeeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int  # enrollment_fee.id ou student_option.id
    enrollment_id: int
    category_name: str
    amount: float  # total dû
    paid: float  # somme des paiements complétés
    remaining: float
    status: str  # pending/partial/paid/waived
    is_optional: bool = False  # True pour les options facultatives
    option_name: str | None = None  # nom de l'option si facultatif


class StudentEnrollmentFeeListResponse(BaseModel):
    items: list[StudentEnrollmentFeeResponse]


class SchoolInfoUpdate(BaseModel):
    school_name: str | None = None
    address: str | None = None
    phone: str | None = None
    email: str | None = None
    logo_url: str | None = None
    ministry_code: str | None = None
