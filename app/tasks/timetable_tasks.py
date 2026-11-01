"""Tache Celery — generation asynchrone de l'emploi du temps."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.celery_app import celery_app
from app.core.config import settings
from app.core.database import current_tenant_id
from app.services import timetable_generation
from app.services.timetable_generation import TimetableGenerationError

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name="timetable.generate")  # type: ignore[misc]
def generate_timetable_task(
    self: Any,
    tenant_id: str,
    class_id: int,
    academic_year_id: int,
    assignments_data: list[dict[str, Any]],
    day_names: list[str],
    day_start_hour: int,
    day_end_hour: int,
    slot_duration_minutes: int,
    room_id: int | None,
) -> dict[str, Any]:
    """Genere un emploi du temps via OR-Tools et persiste les creneaux en DB."""
    try:
        return asyncio.run(
            _generate_async(
                tenant_id=tenant_id,
                class_id=class_id,
                academic_year_id=academic_year_id,
                assignments_data=assignments_data,
                day_names=day_names,
                day_start_hour=day_start_hour,
                day_end_hour=day_end_hour,
                slot_duration_minutes=slot_duration_minutes,
                room_id=room_id,
            )
        )
    except TimetableGenerationError as exc:
        # An expected refusal: the transaction rolled back, the schedule is intact.
        logger.warning("Timetable generation refused for class=%s: %s", class_id, exc)
        return {"slots": [], "error": str(exc)}
    except Exception as exc:
        logger.exception("Timetable generation failed for tenant=%s class=%s", tenant_id, class_id)
        raise exc


@asynccontextmanager
async def _tenant_timetable_session(tenant_id: str) -> AsyncIterator[AsyncSession]:
    """Always close tenant connections and restore context, even on failure."""
    token = current_tenant_id.set(tenant_id)
    engine = None
    try:
        url = settings.DATABASE_URL.format(tenant=tenant_id)
        engine = create_async_engine(url, echo=False)
        factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with factory() as session:
            yield session
    finally:
        if engine is not None:
            try:
                await engine.dispose()
            except Exception:
                # The work is already committed or rolled back: closing must not change the outcome.
                logger.exception("Could not close the connections of tenant=%s", tenant_id)
        current_tenant_id.reset(token)


async def _generate_async(
    tenant_id: str,
    class_id: int,
    academic_year_id: int,
    assignments_data: list[dict[str, Any]],
    day_names: list[str],
    day_start_hour: int,
    day_end_hour: int,
    slot_duration_minutes: int,
    room_id: int | None,
) -> dict[str, Any]:
    """Corps async de la generation : une session tenant, une transaction."""
    settings_grid = timetable_generation.GridSettings(
        day_names=day_names,
        day_start_hour=day_start_hour,
        day_end_hour=day_end_hour,
        slot_duration_minutes=slot_duration_minutes,
    )
    async with _tenant_timetable_session(tenant_id) as db:
        return await timetable_generation.generate_class_timetable(
            db,
            class_id=class_id,
            academic_year_id=academic_year_id,
            assignments_data=assignments_data,
            room_id=room_id,
            settings=settings_grid,
        )
