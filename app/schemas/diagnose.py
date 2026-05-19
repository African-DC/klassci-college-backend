"""Schemas for the platform diagnostics endpoint."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

CheckStatus = Literal["ok", "degraded", "down"]


class HealthCheck(BaseModel):
    component: str
    status: CheckStatus
    message: str | None = None


class PlatformHealth(BaseModel):
    overall: CheckStatus
    checks: list[HealthCheck]
    timestamp: datetime
