"""Router pièces jointes élève — /admin/document-types + /admin/students/{id}/documents.

Pas de `from __future__ import annotations` (DELETE 204 `-> None`, cf. no-pep563-with-204).
"""

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import TokenData, get_current_user, get_tenant_db, require_permission
from app.schemas.attachment import DocumentTypeResponse, StudentDocumentResponse
from app.services import attachment_service
from app.utils.file_upload import save_document_upload

router = APIRouter(prefix="/admin", tags=["student-documents"])


@router.get("/document-types", response_model=list[DocumentTypeResponse])
async def list_document_types(
    _: None = require_permission("admin:students:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> list[DocumentTypeResponse]:
    """Catalogue des types de document (pour le sélecteur, extensible)."""
    types = await attachment_service.list_document_types(db)
    return [DocumentTypeResponse.model_validate(t) for t in types]


@router.get("/students/{student_id}/documents", response_model=list[StudentDocumentResponse])
async def list_student_documents(
    student_id: int,
    _: None = require_permission("admin:students:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> list[StudentDocumentResponse]:
    docs = await attachment_service.list_student_documents(db, student_id)
    return [StudentDocumentResponse.model_validate(d) for d in docs]


@router.post(
    "/students/{student_id}/documents",
    response_model=StudentDocumentResponse,
    status_code=201,
)
async def upload_student_document(
    student_id: int,
    document_type: str = Form(...),
    file: UploadFile = File(...),
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("admin:students:update"),
    db: AsyncSession = Depends(get_tenant_db),
) -> StudentDocumentResponse:
    """Téléverse un document pour un élève (type sélectionné ou créé à la volée)."""
    url, mime = await save_document_upload(file, prefix=f"s{student_id}")
    doc = await attachment_service.add_student_document(
        db,
        student_id,
        document_type=document_type,
        file_url=url,
        file_name=file.filename,
        mime_type=mime,
        uploaded_by=current_user.user_id,
    )
    return StudentDocumentResponse.model_validate(doc)


@router.delete(
    "/students/{student_id}/documents/{doc_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_student_document(
    student_id: int,
    doc_id: int,
    _: None = require_permission("admin:students:update"),
    db: AsyncSession = Depends(get_tenant_db),
) -> None:
    await attachment_service.delete_student_document(db, student_id, doc_id)
