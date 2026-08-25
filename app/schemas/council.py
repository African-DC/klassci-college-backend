"""Schémas Pydantic pour le procès-verbal du conseil de classe."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------


class CouncilMinutesGenerateRequest(BaseModel):
    class_id: int
    trimester: int = Field(ge=1, le=3)
    academic_year_id: int
    main_teacher_name: str | None = None
    director_name: str | None = None
    dren_name: str | None = None
    notes: str | None = None


class DecisionOverrideRequest(BaseModel):
    final_decision: str = Field(..., pattern=r"^(passage|repechage|redoublement|exclusion)$")
    override_reason: str = Field(..., min_length=3, max_length=1000)


class CouncilDecisionBatchItem(BaseModel):
    student_id: int
    final_decision: str = Field(..., pattern=r"^(passage|repechage|redoublement|exclusion)$")
    override_reason: str | None = Field(None, max_length=1000)


class CouncilDecisionsBatchRequest(BaseModel):
    decisions: list[CouncilDecisionBatchItem]


# ---------------------------------------------------------------------------
# Response — Student Decision
# ---------------------------------------------------------------------------


class CouncilStudentDecisionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    student_id: int
    student_name: str
    average: Decimal | None
    rank: int | None
    absence_count: int
    auto_decision: str
    final_decision: str | None
    override_reason: str | None


# ---------------------------------------------------------------------------
# Response — Council Minutes
# ---------------------------------------------------------------------------


class CouncilMinutesResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    class_id: int
    class_name: str
    academic_year_id: int
    trimester: int
    main_teacher_name: str | None
    director_name: str | None
    dren_name: str | None
    notes: str | None
    generated_at: datetime | None
    is_published: bool
    decisions: list[CouncilStudentDecisionResponse]
    created_at: datetime
    updated_at: datetime


class CouncilMinutesPdfResponse(BaseModel):
    pdf_url: str
    message: str
