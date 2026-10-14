"""Unique décision LV2 : colonne du niveau dans la base isolée du tenant.

Aucun nom affiché, code national, variable globale ni cache partagé entre
établissements n'entre dans cette décision métier.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessValidationError
from app.models.academic import Class, Level


LV2_FORBIDDEN_MESSAGE = "La LV2 n'est pas autorisée dans ce niveau par votre établissement."


async def lv2_allowed_for_class(db: AsyncSession, class_id: int) -> bool:
    statement = (
        select(Level.lv2_enabled)
        .join(Class, Class.level_id == Level.id)
        .where(Class.id == class_id)
    )
    enabled = (await db.execute(statement)).scalar_one_or_none()
    if enabled is None:
        raise BusinessValidationError(f"Classe {class_id} introuvable pour la règle LV2.")
    return bool(enabled)


async def ensure_lv2_allowed(db: AsyncSession, class_id: int, lv2: object) -> None:
    if lv2 is not None and not await lv2_allowed_for_class(db, class_id):
        raise BusinessValidationError(LV2_FORBIDDEN_MESSAGE)
