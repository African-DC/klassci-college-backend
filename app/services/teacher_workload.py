"""Charge hebdomadaire d'un enseignant : les heures des matières résolues vers lui."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.resolved_teaching import resolved_class_subjects


async def teacher_weekly_hours(db: AsyncSession, teacher_id: int) -> int:
    """Heures par semaine : chaque (classe, matière) résolue vers cet enseignant compte ses heures.

    La règle de résolution vit dans `resolved_teaching`. Une seule requête.
    """
    resolved = resolved_class_subjects(teacher_id).subquery()
    stmt = select(func.coalesce(func.sum(resolved.c.hours), 0))
    return int((await db.execute(stmt)).scalar() or 0)
