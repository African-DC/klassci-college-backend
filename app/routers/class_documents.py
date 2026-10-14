"""Router documents PDF pour une classe (liste de classe, etc.).

Séparé d'`admin.py` (1300+ LOC) et de `enrollments.py` pour rester
sous la limite no-god-code. Pattern miroir de `student_documents.py`.
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_tenant_db, require_permission
from app.routers._pdf_helpers import pdf_response
from app.services import cahier_texte_service, class_roster_service, class_sheets_service
from app.services.class_roster_filters import RosterFilters

router = APIRouter(prefix="/admin/classes", tags=["admin", "class-documents"])


def _roster_filters(
    genre: str | None = Query(None, pattern="^(M|F)$"),
    age_min: int | None = Query(None, ge=0, le=120),
    age_max: int | None = Query(None, ge=0, le=120),
    nationalities: list[str] | None = Query(None),
    assignment_statuses: list[str] | None = Query(None),
    is_repeater: bool | None = Query(None),
    is_new_student: bool | None = Query(None),
) -> RosterFilters:
    """Critères partagés entre PDF, Word et source Excel ; validation sans ambiguïté."""
    if age_min is not None and age_max is not None and age_min > age_max:
        raise HTTPException(422, detail="L'âge minimum ne peut pas dépasser l'âge maximum")
    invalid_nationality = any(not n.strip() or len(n) > 60 for n in nationalities or ())
    if nationalities and (len(nationalities) > 30 or invalid_nationality):
        raise HTTPException(422, detail="Sélectionnez au maximum 30 nationalités valides")
    allowed = {"affecte", "reaffecte", "non_affecte"}
    if assignment_statuses and (
        len(assignment_statuses) > 3 or not set(assignment_statuses).issubset(allowed)
    ):
        raise HTTPException(422, detail="Statut d'affectation invalide")
    return RosterFilters(
        genre=genre,
        age_min=age_min,
        age_max=age_max,
        nationalities=tuple(nationalities or ()),
        assignment_statuses=tuple(assignment_statuses or ()),
        is_repeater=is_repeater,
        is_new_student=is_new_student,
    )


@router.get(
    "/{class_id}/roster/data",
    summary="Élèves de la liste de classe filtrée (source commune PDF, Word et Excel)",
)
async def get_class_roster_data(
    class_id: int,
    filters: RosterFilters = Depends(_roster_filters),
    _: None = require_permission("admin:students:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict:
    """Ne retourne que les inscriptions validées et non archivées de l'année courante."""
    return await class_roster_service.get_class_roster_data(db, class_id, filters)


@router.get(
    "/{class_id}/roster",
    summary="Liste de classe (PDF) — effectif + matricule + tel parent urgence",
)
async def get_class_roster_pdf(
    class_id: int,
    filters: RosterFilters = Depends(_roster_filters),
    _: None = require_permission("admin:students:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> Response:
    """Génère le PDF de la liste de classe (élèves inscrits AY courante).

    Usage : conseil de classe, sortie scolaire, appel papier secrétariat.
    Tri par nom de famille puis prénom. Photo miniature ou initiales.
    """
    return await pdf_response(
        lambda: class_roster_service.get_class_roster_pdf(db, class_id, filters),
        filename=f"liste-classe-{class_id}.pdf",
        error_context=f"liste de classe {class_id}",
    )


@router.get(
    "/{class_id}/roster.docx",
    summary="Liste de classe (Word) — identité, naissance, nationalité, qualité et affectation",
)
async def get_class_roster_word(
    class_id: int,
    filters: RosterFilters = Depends(_roster_filters),
    _: None = require_permission("admin:students:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> Response:
    """Exporter les élèves validés de l'année courante en document Word éditable."""
    content = await class_roster_service.get_class_roster_docx(db, class_id, filters)
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="liste-classe-{class_id}.docx"'},
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
    à cocher au stylo. Paysage A4. Pas de document officiel ni de sceau numérique.
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
    subject_id: int | None = Query(None, description="Pré-remplit la matière dans l'en-tête"),
    trimester: int | None = Query(None, ge=1, le=3, description="Pré-remplit le trimestre"),
    _: None = require_permission("admin:students:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> Response:
    """Feuille de travail imprimable pour reporter les notes au stylo (AY courante).

    Tableau : N° / Matricule / Nom, puis `columns` colonnes Note vides et une
    colonne Moyenne vide. Paysage A4. Pas de document officiel ni de sceau numérique.
    Matière et trimestre optionnels : pré-remplissent l'en-tête si fournis.
    """
    return await pdf_response(
        lambda: class_sheets_service.get_grade_sheet_pdf(
            db, class_id, columns, subject_id, trimester
        ),
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
    A4. Pas de document officiel ni de sceau numérique.
    """
    return await pdf_response(
        lambda: cahier_texte_service.get_cahier_texte_pdf(db, class_id, start, end),
        filename=f"cahier-texte-{class_id}.pdf",
        error_context=f"cahier de texte {class_id}",
    )
