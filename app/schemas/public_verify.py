"""Strict response contracts for public document verification endpoints."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

PublicVerificationStatus = Literal["active", "revoked", "superseded", "expired"]
FileVerificationStatus = Literal["matching", "modified"]


class PublicVerificationSchema(BaseModel):
    """Base contract that forbids undeclared public response fields."""

    model_config = ConfigDict(extra="forbid", strict=True)


class PublicVerificationResponse(PublicVerificationSchema):
    """Non-identifying institutional document verification result."""

    valid: bool
    status: PublicVerificationStatus
    scheme: str
    document_type: str
    issued_at: datetime | None
    expires_at: datetime | None
    school_name: str
    signature_algorithm: str | None
    key_id: str | None
    file_verification_available: bool


class PublicFileVerificationResponse(PublicVerificationSchema):
    """Result of comparing an uploaded PDF with its issued digest."""

    valid: bool
    matches: bool
    status: FileVerificationStatus
    signature_valid: bool
    document_status: PublicVerificationStatus


class PublicFileVerificationUnavailableResponse(PublicVerificationSchema):
    """Result returned when an issued document has no stored file digest."""

    valid: Literal[False]
    matches: Literal[False]
    status: Literal["unavailable"]
    code: Literal["FILE_VERIFICATION_UNAVAILABLE"]
    signature_valid: bool
    document_status: PublicVerificationStatus


class PublicVerificationErrorResponse(PublicVerificationSchema):
    """Non-identifying error returned by public verification endpoints."""

    detail: str
    code: Literal["NOT_FOUND", "INVALID_PDF", "FILE_TOO_LARGE"]
