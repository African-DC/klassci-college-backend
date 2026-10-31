"""Recurring non-teaching events: school-wide or class-specific."""
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.dependencies import TokenData, get_current_user, get_tenant_db, require_permission
from app.schemas.schedule_event import ScheduleEventCreate, ScheduleEventResponse
from app.services import schedule_event_service as service

router = APIRouter(prefix="/timetable/events", tags=["timetable"])


@router.get("", response_model=list[ScheduleEventResponse])
async def list_events(
    academic_year_id: int = Query(..., gt=0),
    class_id: int | None = Query(None, gt=0),
    _: None = require_permission("timetable:read"),
    db: AsyncSession = Depends(get_tenant_db),
):
    return await service.list_events(db, academic_year_id=academic_year_id, class_id=class_id)


@router.post("", response_model=ScheduleEventResponse, status_code=status.HTTP_201_CREATED)
async def create_event(
    data: ScheduleEventCreate,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("timetable:write"),
    db: AsyncSession = Depends(get_tenant_db),
):
    return await service.save_event(db, data, current_user.user_id)


@router.put("/{event_id}", response_model=ScheduleEventResponse)
async def update_event(
    event_id: int, data: ScheduleEventCreate,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("timetable:write"),
    db: AsyncSession = Depends(get_tenant_db),
):
    return await service.save_event(db, data, current_user.user_id, event_id)


@router.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_event(
    event_id: int,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("timetable:write"),
    db: AsyncSession = Depends(get_tenant_db),
):
    await service.remove_event(db, event_id, current_user.user_id)
