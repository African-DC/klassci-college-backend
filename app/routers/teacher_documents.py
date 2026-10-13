"""Exports enseignants — filtre et génération centralisés, droits read uniquement."""
from typing import Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_tenant_db, require_permission
from app.routers._pdf_helpers import binary_response
from app.services import teacher_exports as exports

router = APIRouter(prefix="/admin/teachers", tags=["teacher-documents"])


class TeacherExportRequest(BaseModel):
    mode: Literal["directory", "assignments"] = "directory"
    academic_year_id: int | None = Field(None, gt=0)
    class_ids: list[int] = Field(default_factory=list, max_length=100)
    level_ids: list[int] = Field(default_factory=list, max_length=100)
    series_ids: list[int] = Field(default_factory=list, max_length=100)
    subject_ids: list[int] = Field(default_factory=list, max_length=100)
    columns: list[str] = Field(default_factory=lambda: exports.DEFAULTS.copy(), min_length=1, max_length=11)
    group: str = "none"
    orientation: Literal["auto", "portrait", "landscape"] = "auto"


@router.get("/export-options")
async def export_options(
    _: None = require_permission("admin:teachers:read"),
    db: AsyncSession = Depends(get_tenant_db),
):
    return await exports.filters(db)


@router.post("/export/{format}")
async def export_teachers(
    format: Literal["pdf", "docx", "xlsx"],
    payload: TeacherExportRequest,
    preview: bool = Query(False),
    _: None = require_permission("admin:teachers:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> Response:
    """POST pour éviter les URL à 100 IDs. PDF preview inline, autres formats attachment."""
    selection = exports.Selection(
        year_id=payload.academic_year_id, class_ids=payload.class_ids,
        level_ids=payload.level_ids, series_ids=payload.series_ids,
        subject_ids=payload.subject_ids, columns=payload.columns,
        group=payload.group, orientation=payload.orientation, mode=payload.mode,
    )
    async def build() -> bytes:
        school, rows = await exports.load(db, selection)
        if format == "pdf":
            return exports.render_pdf(selection, school, rows)
        if format == "docx":
            return exports.render_docx(selection, school, rows)
        return exports.render_xlsx(selection, school, rows)

    return await binary_response(
        build, filename=f"liste-enseignants.{format}",
        media_type=exports.MIME[format],
        error_context="export des enseignants",
        disposition="inline" if preview and format == "pdf" else "attachment",
    )
