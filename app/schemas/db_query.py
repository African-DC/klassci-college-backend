"""Schemas for the raw-SQL execution endpoint."""

import re

from pydantic import BaseModel, Field, field_validator


class DBQueryRequest(BaseModel):
    tenant_slug: str = Field(..., description="Target tenant DB. Use 'local' for the dev DB.")
    sql: str = Field(..., min_length=1, max_length=10_000)
    dry_run: bool = Field(
        True,
        description="True = analyse + warnings only. False = execute + audit log.",
    )
    limit: int = Field(1000, ge=1, le=10_000)

    @field_validator("sql")
    @classmethod
    def reject_multi_statement(cls, v: str) -> str:
        non_empty = [s.strip() for s in v.split(";") if s.strip()]
        if len(non_empty) > 1:
            raise ValueError(
                "Multi-statement queries are rejected. Send one statement per request."
            )
        return v.strip().rstrip(";")

    @field_validator("tenant_slug")
    @classmethod
    def validate_slug(cls, v: str) -> str:
        if v == "local" or re.match(r"^[a-z0-9][a-z0-9\-]{0,61}[a-z0-9]$", v):
            return v
        raise ValueError("Invalid tenant_slug")


class DBQueryWarning(BaseModel):
    code: str
    message: str
    severity: str  # "info" | "warning" | "danger"


class DBQueryResponse(BaseModel):
    tenant_slug: str
    dry_run: bool
    warnings: list[DBQueryWarning]
    rowcount: int | None = None
    columns: list[str] = []
    rows: list[list[object]] = []
    elapsed_ms: float | None = None
    truncated: bool = False
