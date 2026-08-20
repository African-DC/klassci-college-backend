"""Billets d'annulation de zéro : autorisation de rattrapage et son document."""

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import TokenData, get_current_user, get_tenant_db, require_permission
from app.routers._pdf_helpers import pdf_response
from app.schemas.school_life import RetakeAuthorizationCreate, RetakeAuthorizationResponse
from app.services._document_verification_helper import render_verification
from app.services.pdf import generate_zero_cancellation_pdf
from app.services.school_life import retake_service

router = APIRouter(
    prefix="/school-life/retake-authorizations", tags=["school-life", "retake-authorizations"]
)


@router.post("", response_model=RetakeAuthorizationResponse, status_code=201)
async def create_retake_authorization(
    data: RetakeAuthorizationCreate,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("documents:zero-cancellation"),
    db: AsyncSession = Depends(get_tenant_db),
) -> RetakeAuthorizationResponse:
    """Rouvre les évaluations manquées d'un élève sur une période donnée.

    Refusé si une des évaluations visées n'est pas marquée « absent » pour cet
    élève : un billet d'annulation de zéro n'a rien à annuler sur une épreuve
    que l'élève a passée.
    """
    return await retake_service.create_authorization(db, data, actor_id=current_user.user_id)


@router.get("", response_model=list[RetakeAuthorizationResponse])
async def list_retake_authorizations(
    academic_year_id: int | None = Query(None),
    trimester: int | None = Query(None, ge=1, le=3),
    student_id: int | None = Query(None),
    _: None = require_permission("documents:zero-cancellation"),
    db: AsyncSession = Depends(get_tenant_db),
) -> list[RetakeAuthorizationResponse]:
    """Autorisations délivrées, de la plus récente à la plus ancienne."""
    return await retake_service.list_authorizations(
        db,
        academic_year_id=academic_year_id,
        trimester=trimester,
        student_id=student_id,
    )


@router.get("/{authorization_id}/document.pdf", summary="Billet d'annulation de zéro (PDF)")
async def get_retake_document(
    authorization_id: int,
    _: None = require_permission("documents:zero-cancellation"),
    db: AsyncSession = Depends(get_tenant_db),
) -> Response:
    """Imprime le billet, scellé parce qu'il modifie le statut de notes."""
    data = await retake_service.compose_document_data(db, authorization_id)
    settings = data["school_settings"]

    async def _generate() -> bytes:
        return await render_verification(
            db,
            data["verification"],
            lambda: generate_zero_cancellation_pdf(data, settings),
        )

    return await pdf_response(
        _generate,
        filename=f"annulation-zero-{data['student_last_name']}-{authorization_id}.pdf",
        error_context=f"billet d'annulation de zéro {authorization_id}",
    )
