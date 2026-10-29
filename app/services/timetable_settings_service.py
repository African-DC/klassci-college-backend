"""Réglages horaires de l'emploi du temps, propres à chaque établissement."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditAction, audit_log
from app.models.academic import SchoolSettings
from app.schemas.admin import TimetableSettingsUpdate
from app.services.admin_service import get_school_settings


async def update_timetable_settings(
    db: AsyncSession, data: TimetableSettingsUpdate, *, updated_by: int
) -> SchoolSettings:
    """Persist and audit school-specific timetable rules."""
    school = await get_school_settings(db)
    values = data.model_dump()
    previous = {key: getattr(school, key) for key in values}
    if previous == values:
        return school
    async with db.begin_nested():
        for key, value in values.items():
            setattr(school, key, value)
        await db.flush()
        await audit_log(
            db,
            entity_type="school_settings",
            action=AuditAction.UPDATE,
            user_id=updated_by,
            entity_id=school.id,
            old_values=previous,
            new_values=values,
        )
    await db.commit()
    return await get_school_settings(db)
