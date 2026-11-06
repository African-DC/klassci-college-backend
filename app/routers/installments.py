"""Router tranches — grille de l'établissement et échéancier d'une inscription."""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import TokenData, get_current_user, get_tenant_db, require_permission
from app.core.exceptions import BusinessValidationError
from app.models.academic import AcademicYear, Class
from app.routers._pdf_helpers import binary_response, pdf_response
from app.schemas.installment import (
    EnrollmentPlanUpdate,
    EnrollmentScheduleResponse,
    FeeInstallmentGridUpdate,
    FeeInstallmentResponse,
)
from app.schemas.installment_overview import ScheduleOverviewResponse
from app.services import installments as installment_service
from app.services._school_settings_helper import load_school_settings_for_pdf
from app.services.installments.overview import overview

router = APIRouter(tags=["installments"])

# Situation consolidée : un droit de caisse limité ne permet pas de déduire
# ce qu'une famille doit encore. Toutes caisses ou aucun solde : jamais un
# faux retard construit avec le seul guichet du lecteur.
ScheduleState = Literal[
    "all",
    "late",
    "on_track",
    "settled",
    "unconfigured",
    "partial_schedule",
    "no_fees",
]


@router.get(
    "/admin/fee-installments/schedules",
    response_model=ScheduleOverviewResponse,
    summary="Suivi consolidé des échéanciers par année et classe",
)
async def get_school_schedules(
    academic_year_id: int = Query(..., gt=0),
    class_id: int | None = Query(None, gt=0),
    search: str = Query("", max_length=100),
    state: ScheduleState = Query("all"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    _: None = require_permission("payments:read:all"),
    db: AsyncSession = Depends(get_tenant_db),
) -> ScheduleOverviewResponse:
    """Même assiette et mêmes règles de retard que l'échéancier individuel."""
    return await overview(
        db,
        academic_year_id=academic_year_id,
        class_id=class_id,
        search=search,
        state=state,
        page=page,
        size=size,
    )


@router.get(
    "/admin/fee-installments/schedules/export",
    summary="Exporter le suivi consolidé des échéanciers (Excel ou PDF)",
)
async def export_school_schedules(
    academic_year_id: int = Query(..., gt=0),
    class_id: int | None = Query(None, gt=0),
    search: str = Query("", max_length=100),
    state: ScheduleState = Query("all"),
    export_format: Literal["pdf", "xlsx"] = Query("pdf", alias="format"),
    _: None = require_permission("payments:read:all"),
    db: AsyncSession = Depends(get_tenant_db),
) -> Response:
    """Tous les résultats filtrés, pas seulement la page affichée.

    PDF et Excel sont créés depuis la même situation en mémoire, avec
    l'identité visuelle de l'école. Le plafond de 5 000 est déclaré : aucun
    export tronqué ne peut être présenté comme complet.
    """
    from app.services.installments.overview_documents import (
        generate_overview_pdf,
        generate_overview_xlsx,
    )

    async def make_document() -> bytes:
        year = (
            await db.execute(select(AcademicYear.name).where(AcademicYear.id == academic_year_id))
        ).scalar_one_or_none()
        if not year:
            raise BusinessValidationError("Année scolaire introuvable.")
        class_name = ""
        if class_id is not None:
            name = (
                await db.execute(select(Class.name).where(Class.id == class_id))
            ).scalar_one_or_none()
            if name is None:
                raise BusinessValidationError("Classe introuvable.")
            class_name = str(name)

        # Le plafond est celui de l'ensemble *avant* le filtre d'état.
        # Une école de plus de 5000 inscriptions doit restreindre son périmètre.
        data = await overview(
            db,
            academic_year_id=academic_year_id,
            class_id=class_id,
            search=search,
            state=state,
            page=1,
            size=5000,
        )
        school = await load_school_settings_for_pdf(db)
        options = {
            "year": str(year),
            "class_name": class_name,
            "search": search,
            "state": state,
            "issued_at": datetime.now(),
        }
        if export_format == "xlsx":
            return generate_overview_xlsx(data, school, **options)
        return generate_overview_pdf(data, school, **options)

    filename = f"echeanciers-{academic_year_id}.{export_format}"
    if export_format == "xlsx":
        return await binary_response(
            make_document,
            filename=filename,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            error_context="échéanciers (Excel)",
            disposition="attachment",
        )
    return await pdf_response(
        make_document,
        filename=filename,
        error_context="échéanciers (PDF)",
        disposition="attachment",
    )


@router.get(
    "/admin/fee-installments",
    response_model=list[FeeInstallmentResponse],
    summary="Grille de tranches d'une année scolaire",
)
async def get_grid(
    academic_year_id: int = Query(..., description="Année scolaire concernée"),
    _: None = require_permission("admin:fee-installments:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> list[FeeInstallmentResponse]:
    """Découpage du total obligatoire en tranches, avec leurs échéances."""
    return await installment_service.list_grid(db, academic_year_id)


@router.put(
    "/admin/fee-installments",
    response_model=list[FeeInstallmentResponse],
    summary="Remplacer la grille de tranches d'une année",
)
async def put_grid(
    data: FeeInstallmentGridUpdate,
    academic_year_id: int = Query(..., description="Année scolaire concernée"),
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("admin:fee-installments:write"),
    db: AsyncSession = Depends(get_tenant_db),
) -> list[FeeInstallmentResponse]:
    """Remplacement intégral : la somme des pourcentages doit faire 100 %."""
    return await installment_service.replace_grid(
        db, academic_year_id, data, updated_by=current_user.user_id
    )


@router.get(
    "/enrollments/{enrollment_id}/schedule",
    response_model=EnrollmentScheduleResponse,
    summary="Échéancier applicable à une inscription et état de retard",
)
async def get_schedule(
    enrollment_id: int,
    _: None = require_permission("enrollments:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> EnrollmentScheduleResponse:
    """Accord négocié s'il existe, sinon la grille de l'établissement."""
    return await installment_service.resolve_schedule(db, enrollment_id)


@router.put(
    "/enrollments/{enrollment_id}/schedule",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Fixer un échéancier négocié avec la famille",
)
async def put_schedule(
    enrollment_id: int,
    data: EnrollmentPlanUpdate,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("enrollments:schedule:write"),
    db: AsyncSession = Depends(get_tenant_db),
) -> None:
    """Le total doit correspondre exactement aux frais obligatoires."""
    await installment_service.set_enrollment_plan(
        db, enrollment_id, data, updated_by=current_user.user_id
    )


@router.delete(
    "/enrollments/{enrollment_id}/schedule",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Retirer l'échéancier négocié",
)
async def delete_schedule(
    enrollment_id: int,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("enrollments:schedule:write"),
    db: AsyncSession = Depends(get_tenant_db),
) -> None:
    """La famille repasse sur la grille standard de l'établissement."""
    await installment_service.clear_enrollment_plan(
        db, enrollment_id, updated_by=current_user.user_id
    )
