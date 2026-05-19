"""Schemas for the platform logs endpoint."""

from datetime import datetime

from pydantic import BaseModel, Field


class LogLine(BaseModel):
    timestamp: datetime | None = None
    raw: str


class LogsResponse(BaseModel):
    service: str
    lines: list[LogLine]
    truncated: bool = Field(False, description="True if N exceeded the safety cap")
    redacted_count: int = Field(0, description="Number of secret patterns redacted")
