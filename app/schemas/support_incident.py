"""Public incident contracts: never include traces or server logs."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


IncidentStatus = Literal["new", "in_progress", "waiting", "resolved", "closed"]
IncidentPriority = Literal["low", "normal", "high", "critical"]

class IncidentCreate(BaseModel):
    title: str = Field(min_length=5, max_length=160)
    description: str = Field(min_length=10, max_length=2000)
    reference: str | None = Field(default=None, pattern=r"^[0-9A-Fa-f]{6,16}$")
    source: Literal["web", "mobile", "other"] = "web"

class IncidentUpdate(BaseModel):
    status: IncidentStatus
    priority: IncidentPriority | None = None
    message: str | None = Field(default=None, max_length=2000)

class IncidentReply(BaseModel):
    message: str = Field(min_length=2, max_length=2000)

class IncidentEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    actor_kind: str
    status: str | None
    message: str | None
    created_at: datetime

class IncidentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    reference: str | None
    title: str
    description: str
    status: str
    priority: str
    source: str
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None
    events: list[IncidentEventOut] = Field(default_factory=list)

class IncidentPage(BaseModel):
    items: list[IncidentOut]
    total: int
    page: int
    size: int
