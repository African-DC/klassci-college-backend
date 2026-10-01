"""Corriger la fiche de renseignements, une inscription ou une classe entière.

Le lot sert le comptable qui reprend sa fiche papier classe par classe : il
coche la LV2 de trente élèves d'un coup. Il passe en entier ou pas du tout.
Une moitié de classe enregistrée et l'autre refusée l'obligerait à retrouver,
ligne par ligne, ce qui est passé.
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.audit import AuditAction, audit_log
from app.core.exceptions import BusinessValidationError, NotFoundError
from app.models.academic import Class
from app.models.enrollment import Enrollment
from app.repositories import enrollment_repository as repo
from app.schemas.enrollment import EnrollmentResponse
from app.schemas.enrollment_profile import (
    PROFILE_FIELDS,
    EnrollmentProfileBatchRequest,
    EnrollmentProfileUpdate,
)
from app.services.enrollment_mapper import to_enrollment_response
from app.services.enrollment_profile import (
    LV2_FORBIDDEN_MESSAGE,
    ensure_lv2_allowed,
    level_name_of_class,
)
from app.services.level_codes import LEVELS_WITHOUT_LV2, national_level_code


def _plain(value: object) -> object:
    """Une valeur de colonne telle que le journal JSON peut la garder."""
    return getattr(value, "value", value)


def _sent_fields(data: EnrollmentProfileUpdate) -> set[str]:
    """Les champs de la fiche réellement envoyés, `null` compris."""
    return data.model_fields_set & set(PROFILE_FIELDS)


async def _apply(
    db: AsyncSession, enrollment: Enrollment, data: EnrollmentProfileUpdate, actor: int
) -> None:
    """Écrit les champs envoyés et journalise ceux qui changent vraiment."""
    sent = _sent_fields(data)
    new_values = data.model_dump(include=sent, mode="json")
    old_values = {name: _plain(getattr(enrollment, name)) for name in sent}
    changed = {name for name in sent if old_values[name] != new_values[name]}
    for name in sent:
        setattr(enrollment, name, getattr(data, name))
    await db.flush()
    if not changed:
        return
    await audit_log(
        db,
        entity_type="enrollment",
        action=AuditAction.UPDATE,
        user_id=actor,
        entity_id=enrollment.id,
        old_values={name: old_values[name] for name in changed},
        new_values={name: new_values[name] for name in changed},
    )


async def update_profile(
    db: AsyncSession, enrollment_id: int, data: EnrollmentProfileUpdate, *, updated_by: int
) -> EnrollmentResponse:
    """PATCH d'une fiche : un champ absent reste, un `null` envoyé efface."""
    enrollment = await repo.get_enrollment_by_id(db, enrollment_id)
    if enrollment is None:
        raise NotFoundError("Enrollment", enrollment_id)
    if "lv2" in data.model_fields_set:
        ensure_lv2_allowed(await level_name_of_class(db, enrollment.class_id), data.lv2)

    async with db.begin_nested():
        await _apply(db, enrollment, data, updated_by)
    await db.commit()

    refreshed = await repo.get_enrollment_by_id(db, enrollment_id)
    if refreshed is None:
        raise NotFoundError("Enrollment", enrollment_id)
    return to_enrollment_response(refreshed)


async def _load_batch(db: AsyncSession, ids: list[int]) -> dict[int, Enrollment]:
    stmt = (
        select(Enrollment)
        .where(Enrollment.id.in_(ids))
        .options(selectinload(Enrollment.class_).selectinload(Class.level))
    )
    return {e.id: e for e in (await db.execute(stmt)).scalars().all()}


def _check_batch(request: EnrollmentProfileBatchRequest, found: dict[int, Enrollment]) -> None:
    """Refuse le lot entier, en nommant chaque inscription fautive."""
    missing = sorted(i.enrollment_id for i in request.items if i.enrollment_id not in found)
    if missing:
        raise BusinessValidationError(
            f"Inscriptions introuvables, aucune fiche n'a été modifiée : {missing}"
        )
    lv2_refused: list[int] = []
    for item in request.items:
        level = found[item.enrollment_id].class_.level
        code = national_level_code(level.name if level else None)
        if "lv2" in item.model_fields_set and item.lv2 is not None and code in LEVELS_WITHOUT_LV2:
            lv2_refused.append(item.enrollment_id)
    if lv2_refused:
        raise BusinessValidationError(
            f"{LV2_FORBIDDEN_MESSAGE} Aucune fiche n'a été modifiée. "
            f"Inscriptions concernées : {sorted(lv2_refused)}"
        )


async def update_profiles_in_batch(
    db: AsyncSession, request: EnrollmentProfileBatchRequest, *, updated_by: int
) -> dict[str, Any]:
    """Applique tout le lot dans une transaction, ou rien."""
    found = await _load_batch(db, [item.enrollment_id for item in request.items])
    _check_batch(request, found)
    async with db.begin_nested():
        for item in request.items:
            await _apply(db, found[item.enrollment_id], item, updated_by)
    await db.commit()
    return {"updated": len(request.items)}
