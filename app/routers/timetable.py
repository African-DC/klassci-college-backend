"""Router emploi du temps — CRUD /timetable + génération OR-Tools."""

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import TokenData, get_current_user, get_tenant_db, require_permission
from app.routers._pdf_helpers import pdf_response
from app.schemas.timetable import (
    GenerateTimetableRequest,
    GenerateTimetableResponse,
    TaskStatusResponse,
    TeacherAvailabilityCreate,
    TeacherAvailabilityResponse,
    TeacherAvailabilityUpdate,
    TeacherWeekResponse,
    TimetableSlotCreate,
    TimetableSlotResponse,
    TimetableSlotUpdate,
)
from app.services import teacher_availability_service, timetable_service

router = APIRouter(prefix="/timetable", tags=["timetable"])


# ---------------------------------------------------------------------------
# GET /timetable
# ---------------------------------------------------------------------------


@router.get("", response_model=list[TimetableSlotResponse])
async def list_slots(
    class_id: int | None = Query(None),
    teacher_id: int | None = Query(None),
    academic_year_id: int | None = Query(None),
    _: None = require_permission("timetable:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> list[TimetableSlotResponse]:
    """Liste les créneaux de l'emploi du temps avec filtres optionnels."""
    return await timetable_service.list_slots(
        db,
        class_id=class_id,
        teacher_id=teacher_id,
        academic_year_id=academic_year_id,
    )


# ---------------------------------------------------------------------------
# POST /timetable/generate  — doit être avant /{slot_id}
# ---------------------------------------------------------------------------


@router.post(
    "/generate",
    response_model=GenerateTimetableResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def generate_timetable(
    data: GenerateTimetableRequest,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("timetable:generate"),
) -> GenerateTimetableResponse:
    """Lance la génération OR-Tools de l'emploi du temps (tâche asynchrone)."""
    return timetable_service.trigger_generate(current_user.tenant_id, data)


@router.get("/diagnostic")
async def get_generation_diagnostic(
    class_id: int = Query(...),
    _: None = require_permission("timetable:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict:
    """Diagnostic pre-generation : verifie les prerequis."""
    return await timetable_service.diagnostic_for_class(db, class_id)


@router.post(
    "/auto-generate",
    response_model=GenerateTimetableResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def auto_generate_timetable(
    class_id: int = Query(...),
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("timetable:generate"),
    db: AsyncSession = Depends(get_tenant_db),
) -> GenerateTimetableResponse:
    """Generation automatique intelligente — preserve les slots manuels."""
    return await timetable_service.auto_generate(db, current_user.tenant_id, class_id)


# ---------------------------------------------------------------------------
# GET /timetable/export-pdf
# ---------------------------------------------------------------------------


@router.get("/export-pdf")
async def export_timetable_pdf(
    class_id: int = Query(...),
    _: None = require_permission("timetable:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> Response:
    """Export emploi du temps en PDF (A4 paysage)."""
    return await pdf_response(
        lambda: timetable_service.export_timetable_pdf(db, class_id),
        filename=f"emploi-du-temps-classe-{class_id}.pdf",
        error_context=f"emploi du temps classe {class_id}",
        disposition="attachment",
    )


# ---------------------------------------------------------------------------
# GET /timetable/tasks/{task_id}
# ---------------------------------------------------------------------------


@router.get("/tasks/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(
    task_id: str,
    _: None = require_permission("timetable:read"),
) -> TaskStatusResponse:
    """Retourne le statut d'une tâche de génération."""
    return timetable_service.get_task_status(task_id)


# ---------------------------------------------------------------------------
# POST /timetable/slots
# ---------------------------------------------------------------------------


@router.post(
    "/slots",
    response_model=TimetableSlotResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_slot(
    data: TimetableSlotCreate,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("timetable:write"),
    db: AsyncSession = Depends(get_tenant_db),
) -> TimetableSlotResponse:
    """Crée un créneau manuellement — vérifie les conflits enseignant et classe."""
    return await timetable_service.create_slot(db, data, created_by=current_user.user_id)


# ---------------------------------------------------------------------------
# PATCH /timetable/slots/{slot_id}
# ---------------------------------------------------------------------------


@router.patch("/slots/{slot_id}", response_model=TimetableSlotResponse)
async def update_slot(
    slot_id: int,
    data: TimetableSlotUpdate,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("timetable:write"),
    db: AsyncSession = Depends(get_tenant_db),
) -> TimetableSlotResponse:
    """Met à jour un créneau (patch partiel)."""
    return await timetable_service.update_slot(db, slot_id, data, updated_by=current_user.user_id)


# ---------------------------------------------------------------------------
# DELETE /timetable/slots/{slot_id}
# ---------------------------------------------------------------------------


@router.delete("/slots/{slot_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_slot(
    slot_id: int,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("timetable:write"),
    db: AsyncSession = Depends(get_tenant_db),
) -> None:
    """Supprime un créneau."""
    await timetable_service.delete_slot(db, slot_id, deleted_by=current_user.user_id)


# ---------------------------------------------------------------------------
# Disponibilites enseignant, cote administration
#
# `timetable:write` et non un role en dur : chez ROSTAN c'est le directeur des
# etudes qui saisit ce que l'enseignant lui a dit de vive voix, ailleurs c'est
# le secretariat. L'ecran d'ajout de creneau et la fiche enseignant tapent tous
# les deux ici.
# ---------------------------------------------------------------------------

teachers_router = APIRouter(prefix="/teachers", tags=["timetable"])


@teachers_router.get(
    "/{teacher_id}/availabilities",
    response_model=list[TeacherAvailabilityResponse],
)
async def list_teacher_availabilities(
    teacher_id: int,
    _: None = require_permission("timetable:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> list[TeacherAvailabilityResponse]:
    """Retourne les plages declarees pour un enseignant."""
    return await teacher_availability_service.list_for_teacher(db, teacher_id)


@teachers_router.get("/{teacher_id}/week", response_model=TeacherWeekResponse)
async def get_teacher_week(
    teacher_id: int,
    academic_year_id: int | None = Query(None),
    _: None = require_permission("timetable:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> TeacherWeekResponse:
    """La semaine occupee d'un enseignant : cours ailleurs et plages fermees.

    Sert a montrer l'empechement **avant** le choix de l'horaire, plutot que de
    le refuser apres coup.
    """
    return await teacher_availability_service.week_for_teacher(
        db, teacher_id, academic_year_id=academic_year_id
    )


@teachers_router.post(
    "/{teacher_id}/availabilities",
    response_model=TeacherAvailabilityResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_teacher_availability(
    teacher_id: int,
    data: TeacherAvailabilityCreate,
    _: None = require_permission("timetable:write"),
    db: AsyncSession = Depends(get_tenant_db),
) -> TeacherAvailabilityResponse:
    """Declare une plage pour un enseignant."""
    return await teacher_availability_service.create(db, teacher_id, data)


availability_router = APIRouter(prefix="/teacher-availabilities", tags=["timetable"])


@availability_router.patch(
    "/{av_id}",
    response_model=TeacherAvailabilityResponse,
)
async def update_teacher_availability(
    av_id: int,
    data: TeacherAvailabilityUpdate,
    _: None = require_permission("timetable:write"),
    db: AsyncSession = Depends(get_tenant_db),
) -> TeacherAvailabilityResponse:
    """Rouvre ou referme une plage."""
    return await teacher_availability_service.update(db, av_id, data)


@availability_router.delete("/{av_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_teacher_availability(
    av_id: int,
    _: None = require_permission("timetable:write"),
    db: AsyncSession = Depends(get_tenant_db),
) -> None:
    """Supprime une plage."""
    await teacher_availability_service.remove(db, av_id)
