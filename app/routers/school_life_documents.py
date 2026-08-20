"""Actes de vie scolaire sans registre : demande de dossier et billet d'entrée.

Les deux autres actes (convocation, annulation de zéro) vivent dans leurs
propres routeurs parce qu'ils ont un registre à consulter.
"""

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit_read import audit_read
from app.core.dependencies import TokenData, get_current_user, get_tenant_db, require_permission
from app.routers._pdf_helpers import pdf_response
from app.schemas.school_life import EntrySlipRequest
from app.services._document_verification_helper import render_verification
from app.services.pdf import generate_entry_slip_pdf, generate_school_file_request_pdf
from app.services.school_life import entry_slip_service, school_file_request_service

router = APIRouter(prefix="/school-life", tags=["school-life"])


@router.get(
    "/students/{student_id}/documents/demande-dossier-scolaire.pdf",
    summary="Demande de dossier scolaire (PDF) — courrier vers l'établissement d'origine",
)
async def get_school_file_request(
    student_id: int,
    _read: None = audit_read("document_demande_dossier", param="student_id"),
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("documents:school-file-request"),
    db: AsyncSession = Depends(get_tenant_db),
) -> Response:
    """Réclame le dossier d'un élève à son ancien établissement.

    Le document porte le sceau numérique : il quitte le collège, et
    l'établissement destinataire doit pouvoir vérifier qu'il vient bien de
    l'administration et non de la famille.
    """
    data = await school_file_request_service.compose_request_data(
        db, student_id, actor_id=current_user.user_id
    )
    settings = data["school_settings"]

    async def _generate() -> bytes:
        return await render_verification(
            db,
            data["verification"],
            lambda: generate_school_file_request_pdf(data, settings),
        )

    return await pdf_response(
        _generate,
        filename=f"demande-dossier-{data['student_last_name']}.pdf",
        error_context=f"demande de dossier scolaire élève {student_id}",
    )


@router.post(
    "/attendance-records/{record_id}/entry-slip.pdf",
    summary="Billet d'entrée (PDF) — régularise une absence et réadmet en cours",
)
async def issue_entry_slip(
    record_id: int,
    payload: EntrySlipRequest,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("documents:entry-slip"),
    db: AsyncSession = Depends(get_tenant_db),
) -> Response:
    """Ferme l'absence visée et imprime le billet de réadmission.

    Verbe POST et non GET : l'appel modifie le cahier d'appel. Le billet ne
    porte pas de sceau numérique — c'est une pièce interne imprimée par
    dizaines chaque matin, sa référence en pied suffit à la retrouver.
    """
    data = await entry_slip_service.close_absence_and_compose(
        db,
        record_id,
        resume_date=payload.resume_date,
        notes=payload.notes,
        actor_id=current_user.user_id,
    )
    settings = data["school_settings"]

    async def _generate() -> bytes:
        return generate_entry_slip_pdf(data, settings)

    return await pdf_response(
        _generate,
        filename=f"billet-entree-{data['student_last_name']}.pdf",
        error_context=f"billet d'entrée pour l'appel {record_id}",
    )
