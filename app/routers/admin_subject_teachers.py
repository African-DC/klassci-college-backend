"""Enseignants par matière : répartition des créneaux de l'emploi du temps."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_tenant_db, require_permission
from app.schemas.subject_teachers import SubjectSlotCountsResponse
from app.services import subject_teachers as subject_teachers_service

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/subjects/{subject_id}/slot-counts", response_model=SubjectSlotCountsResponse)
async def get_subject_slot_counts(
    subject_id: int,
    _: None = require_permission("admin:subjects:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> SubjectSlotCountsResponse:
    """Nombre de créneaux de l'emploi du temps par enseignant, pour une matière."""
    return await subject_teachers_service.slot_counts_for_subject(db, subject_id)
