"""Router documents PDF pour une classe (liste de classe, etc.).

Séparé d'`admin.py` (1300+ LOC) et de `enrollments.py` pour rester
sous la limite no-god-code. Pattern miroir de `student_documents.py`.
"""

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_tenant_db, require_permission
from app.services import class_roster_service

router = APIRouter(prefix="/admin/classes", tags=["admin", "class-documents"])


@router.get(
    "/{class_id}/roster",
    summary="Liste de classe (PDF) — effectif + matricule + tel parent urgence",
)
async def get_class_roster_pdf(
    class_id: int,
    _: None = require_permission("admin:students:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> Response:
    """Génère le PDF de la liste de classe (élèves inscrits AY courante).

    Usage : conseil de classe, sortie scolaire, appel papier secrétariat.
    Tri par nom de famille puis prénom. Photo miniature ou initiales.
    """
    pdf_bytes = await class_roster_service.get_class_roster_pdf(db, class_id)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'inline; filename="liste-classe-{class_id}.pdf"'
            )
        },
    )
