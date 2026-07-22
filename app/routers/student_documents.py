"""Router student_documents — documents officiels par eleve (certificat, attestation, ...)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import TokenData, get_current_user, get_tenant_db, require_permission
from app.routers._pdf_helpers import pdf_response
from app.services import document_issuance_service, student_documents_service
from app.services._document_verification_helper import render_verification
from app.services.pdf_service import (
    generate_attendance_certificate_pdf,
    generate_certificate_scolarite_pdf,
)

router = APIRouter(prefix="/students", tags=["student-documents"])


class RevokeDocumentSealRequest(BaseModel):
    reason: str = Field(min_length=5, max_length=500)

    @field_validator("reason", mode="before")
    @classmethod
    def normalize_reason(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


@router.get("/{student_id}/documents/certificat-scolarite.pdf")
async def get_certificat_scolarite(
    student_id: int,
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_tenant_db),
) -> Response:
    """Genere le certificat de scolarite officiel d'un eleve.

    Permission scoping :
    - admin / staff / teacher : doit avoir la permission ``documents:certificate``
    - parent : doit etre lie a l'eleve (via parent_student)
    - student : ne peut acceder qu'a son propre certificat

    Renvoie 422 si l'eleve n'a pas d'inscription valide pour l'annee courante.
    """
    await student_documents_service.verify_document_access(
        db,
        current_user_id=current_user.user_id,
        student_id=student_id,
        permission_slug="documents:certificate",
    )

    data = await student_documents_service.compose_certificate_data(db, student_id)
    settings = data["school_settings"]

    last_name = data["student"]["last_name"]
    safe_year = data["academic_year_name"].replace(" ", "_").replace("/", "-")
    filename = f"certificat_scolarite_{last_name}_{safe_year}.pdf"

    async def _generate() -> bytes:
        return await render_verification(
            db,
            data["verification"],
            lambda: generate_certificate_scolarite_pdf(data, settings),
        )

    return await pdf_response(
        _generate,
        filename=filename,
        error_context=f"certificat de scolarité élève {student_id}",
    )


@router.get("/{student_id}/documents/attestation-frequentation.pdf")
async def get_attestation_frequentation(
    student_id: int,
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_tenant_db),
) -> Response:
    """Genere l'attestation de frequentation officielle d'un eleve.

    Permission scoping :
    - admin / staff / teacher : doit avoir la permission ``documents:attendance``
    - parent : doit etre lie a l'eleve (via parent_student)
    - student : ne peut acceder qu'a sa propre attestation

    Renvoie 422 si l'eleve n'a pas d'inscription valide pour l'annee courante.
    """
    await student_documents_service.verify_document_access(
        db,
        current_user_id=current_user.user_id,
        student_id=student_id,
        permission_slug="documents:attendance",
    )

    data = await student_documents_service.compose_attendance_certificate_data(db, student_id)
    settings = data["school_settings"]

    last_name = data["student"]["last_name"]
    safe_year = data["academic_year_name"].replace(" ", "_").replace("/", "-")
    filename = f"attestation_frequentation_{last_name}_{safe_year}.pdf"

    async def _generate() -> bytes:
        return await render_verification(
            db,
            data["verification"],
            lambda: generate_attendance_certificate_pdf(data, settings),
        )

    return await pdf_response(
        _generate,
        filename=filename,
        error_context=f"attestation fréquentation élève {student_id}",
    )


@router.post("/document-issuances/{seal_code}/revoke")
async def revoke_document_seal(
    seal_code: str,
    payload: RevokeDocumentSealRequest,
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_tenant_db),
    _: None = require_permission("documents:revoke"),
) -> dict[str, str]:
    """Révoque définitivement un sceau institutionnel après justification."""
    issuance = await document_issuance_service.get_issuance_by_code(db, seal_code)
    if issuance is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sceau introuvable.")
    try:
        revoked = await document_issuance_service.revoke_document(
            db,
            issuance.id,
            reason=payload.reason,
            revoked_by=current_user.user_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return {"status": revoked.status, "seal_code": revoked.seal_code or revoked.cev_code}
