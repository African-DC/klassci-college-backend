"""Schémas des pièces jointes élève."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DocumentTypeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class StudentDocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    student_id: int
    document_type: str
    file_url: str
    file_name: str | None = None
    mime_type: str | None = None
    uploaded_by: int | None = None
    created_at: datetime
