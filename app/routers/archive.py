"""Router corbeille — ce qui a été mis de côté, toutes fiches confondues.

Un seul écran pour les cinq entités archivables : celui qui cherche une fiche
disparue ne sait pas toujours de quelle sorte elle était, et surtout il ne
devrait pas avoir à le savoir pour la retrouver.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_tenant_db, require_permission
from app.schemas.archive import ArchiveListResponse
from app.services import recycle_bin

router = APIRouter(prefix="/admin/archive", tags=["archive"])


@router.get("", response_model=ArchiveListResponse)
async def list_archive(
    entity_type: str | None = Query(
        None,
        max_length=50,
        description="Ne montrer qu'une sorte de fiche : student, parent, teacher, staff, enrollment.",
    ),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=100),
    _: None = require_permission("archive:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> ArchiveListResponse:
    """Corbeille paginée, de la fiche la plus récemment mise de côté à la plus ancienne."""
    return await recycle_bin.list_bin(db, entity_type=entity_type, page=page, size=size)
