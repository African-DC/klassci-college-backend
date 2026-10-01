"""Router fiche de renseignements — une classe, ou toutes les classes de l'année.

Le chemin littéral `/information-sheet` et le chemin paramétré
`/classes/{class_id}/information-sheet` ne se recouvrent pas ; le littéral est
tout de même déclaré en premier, par principe.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_tenant_db, require_permission
from app.schemas.class_information_sheet import InformationSheetResponse
from app.services import class_information_sheet

router = APIRouter(tags=["information-sheet"])


@router.get("/information-sheet", response_model=InformationSheetResponse)
async def school_information_sheet(
    academic_year_id: int | None = Query(
        None, ge=1, description="Année de la fiche. Omise, l'année courante."
    ),
    _: None = require_permission("enrollments:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> InformationSheetResponse:
    """La fiche de toutes les classes qui ont au moins un inscrit sur l'année."""
    return await class_information_sheet.school_sheet(db, academic_year_id)


@router.get("/classes/{class_id}/information-sheet", response_model=InformationSheetResponse)
async def class_information_sheet_route(
    class_id: int,
    academic_year_id: int | None = Query(
        None, ge=1, description="Année de la fiche. Omise, l'année courante."
    ),
    _: None = require_permission("enrollments:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> InformationSheetResponse:
    """La fiche d'une seule classe, triée par nom puis prénom."""
    return await class_information_sheet.class_sheet(db, class_id, academic_year_id)
