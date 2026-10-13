"""Documents enseignants : API commune à l'aperçu PDF, PDF, Word et Excel.

Le RBAC et la session de base passent par les dépendances admin existantes.
Aucune route publique ; aucun ID de tenant choisi par le client.
"""

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_tenant_db, require_permission
from app.routers._pdf_helpers import binary_response, pdf_response
from app.schemas.teacher_directory import TeacherExportOptions, page_orientation
from app.services._school_settings_helper import load_school_settings_for_pdf
from app.services.teacher_directory_documents import render_excel, render_pdf, render_word
from app.services.teacher_directory_service import build_directory, export_choices

router = APIRouter(prefix="/admin/teachers/exports", tags=["admin", "teacher-exports"])

_WORD = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_EXCEL = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("/options")
async def teacher_export_options(
    _: None = require_permission("admin:teachers:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict:
    """Les valeurs réelles du tenant : niveaux, séries, classes, matières, années."""
    return await export_choices(db)


async def _generate(db: AsyncSession, options: TeacherExportOptions, fmt: str) -> bytes:
    # Vérifier la pagination avant de déclencher les lectures et le rendu coûteux.
    page_orientation(options)
    directory = await build_directory(db, options)
    school = await load_school_settings_for_pdf(db)
    if fmt == "pdf":
        return render_pdf(directory, school, options)
    if fmt == "word":
        return render_word(directory, school, options)
    return render_excel(directory, school, options)


@router.post("/preview-pdf")
async def preview_teacher_directory_pdf(
    options: TeacherExportOptions,
    _: None = require_permission("admin:teachers:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> Response:
    return await pdf_response(
        lambda: _generate(db, options, "pdf"),
        filename="liste-enseignants.pdf",
        error_context="aperçu de la liste des enseignants",
        disposition="inline",
    )


@router.post("/pdf")
async def export_teacher_directory_pdf(
    options: TeacherExportOptions,
    _: None = require_permission("admin:teachers:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> Response:
    return await pdf_response(
        lambda: _generate(db, options, "pdf"),
        filename="liste-enseignants.pdf",
        error_context="liste des enseignants",
        disposition="attachment",
    )


@router.post("/word")
async def export_teacher_directory_word(
    options: TeacherExportOptions,
    _: None = require_permission("admin:teachers:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> Response:
    return await binary_response(
        lambda: _generate(db, options, "word"),
        filename="liste-enseignants.docx", media_type=_WORD,
        error_context="liste des enseignants Word", disposition="attachment",
    )


@router.post("/excel")
async def export_teacher_directory_excel(
    options: TeacherExportOptions,
    _: None = require_permission("admin:teachers:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> Response:
    return await binary_response(
        lambda: _generate(db, options, "excel"),
        filename="liste-enseignants.xlsx", media_type=_EXCEL,
        error_context="liste des enseignants Excel", disposition="attachment",
    )
