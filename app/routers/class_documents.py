"""Router documents PDF pour une classe (liste de classe, etc.).

Séparé d'`admin.py` (1300+ LOC) et de `enrollments.py` pour rester
sous la limite no-god-code. Pattern miroir de `student_documents.py`.
"""

from datetime import date

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_tenant_db, require_permission
from app.routers._pdf_helpers import pdf_response
from app.services import cahier_texte_service, class_roster_service, class_sheets_service

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
    return await pdf_response(
        lambda: class_roster_service.get_class_roster_pdf(db, class_id),
        filename=f"liste-classe-{class_id}.pdf",
        error_context=f"liste de classe {class_id}",
    )


@router.get(
    "/{class_id}/attendance-sheet",
    summary="Feuille d'appel vierge (PDF) — colonnes de présence à cocher à la main",
)
async def get_attendance_sheet_pdf(
    class_id: int,
    columns: int = Query(25, ge=5, le=40, description="Nombre de colonnes de présence vides"),
    _: None = require_permission("admin:students:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> Response:
    """Feuille de travail imprimable pour l'appel papier (AY courante).

    Tableau : N° / Matricule / Nom, puis `columns` colonnes vides numérotées
    à cocher au stylo. Paysage A4. Pas de document officiel (ni CEV ni signature).
    """
    return await pdf_response(
        lambda: class_sheets_service.get_attendance_sheet_pdf(db, class_id, columns),
        filename=f"feuille-appel-{class_id}.pdf",
        error_context=f"feuille d'appel {class_id}",
    )


@router.get(
    "/{class_id}/grade-sheet",
    summary="Feuille de notes vierge (PDF) — colonnes de notes + moyenne à remplir à la main",
)
async def get_grade_sheet_pdf(
    class_id: int,
    columns: int = Query(6, ge=1, le=12, description="Nombre de colonnes de notes vides"),
    _: None = require_permission("admin:students:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> Response:
    """Feuille de travail imprimable pour reporter les notes au stylo (AY courante).

    Tableau : N° / Matricule / Nom, puis `columns` colonnes Note vides et une
    colonne Moyenne vide. Paysage A4. Pas de document officiel (ni CEV ni signature).
    """
    return await pdf_response(
        lambda: class_sheets_service.get_grade_sheet_pdf(db, class_id, columns),
        filename=f"feuille-notes-{class_id}.pdf",
        error_context=f"feuille de notes {class_id}",
    )


@router.get(
    "/{class_id}/cahier-texte",
    summary="Cahier de texte (PDF) — séances datées depuis l'EDT, contenu à remplir",
)
async def get_cahier_texte_pdf(
    class_id: int,
    start: date | None = Query(None, description="Début de période (défaut : semaine courante)"),
    end: date | None = Query(None, description="Fin de période (défaut : semaine courante)"),
    _: None = require_permission("admin:students:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> Response:
    """Cahier de texte structuré depuis l'emploi du temps (AY courante).

    Développe les créneaux EDT sur les dates réelles de la période. Colonnes
    Contenu / Travail à faire laissées vides pour l'écriture manuscrite. Paysage
    A4. Pas de document officiel (ni CEV ni signature).
    """
    return await pdf_response(
        lambda: cahier_texte_service.get_cahier_texte_pdf(db, class_id, start, end),
        filename=f"cahier-texte-{class_id}.pdf",
        error_context=f"cahier de texte {class_id}",
    )
