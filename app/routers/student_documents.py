"""Router student_documents — documents officiels par eleve (certificat, attestation, ...)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import TokenData, get_current_user, get_tenant_db
from app.routers._pdf_helpers import pdf_response
from app.services import student_documents_service
from app.services._school_settings_helper import load_school_settings_for_pdf
from app.services.pdf_service import (
    generate_attendance_certificate_pdf,
    generate_certificate_scolarite_pdf,
)

router = APIRouter(prefix="/students", tags=["student-documents"])


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
    settings = await load_school_settings_for_pdf(db)

    last_name = data["student"]["last_name"]
    safe_year = data["academic_year_name"].replace(" ", "_").replace("/", "-")
    filename = f"certificat_scolarite_{last_name}_{safe_year}.pdf"

    async def _generate() -> bytes:
        return generate_certificate_scolarite_pdf(data, settings)

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
    settings = await load_school_settings_for_pdf(db)

    last_name = data["student"]["last_name"]
    safe_year = data["academic_year_name"].replace(" ", "_").replace("/", "-")
    filename = f"attestation_frequentation_{last_name}_{safe_year}.pdf"

    async def _generate() -> bytes:
        return generate_attendance_certificate_pdf(data, settings)

    return await pdf_response(
        _generate,
        filename=filename,
        error_context=f"attestation fréquentation élève {student_id}",
    )
