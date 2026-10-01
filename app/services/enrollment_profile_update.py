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
from app.models.enrollment import Enrollment, PreviousLevel
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
    repeater_status,
)
from app.services.level_codes import LEVELS_WITHOUT_LV2, national_level_code


def _plain(value: object) -> object:
    """Une valeur de colonne telle que le journal JSON peut la garder."""
    return getattr(value, "value", value)


def _sent_fields(data: EnrollmentProfileUpdate) -> set[str]:
    """Les champs de la fiche réellement envoyés, `null` compris."""
    return data.model_fields_set & set(PROFILE_FIELDS)


def _targets(data: EnrollmentProfileUpdate, class_code: PreviousLevel | None) -> dict[str, object]:
    """Les valeurs à écrire : les champs envoyés, plus la qualité qui en découle.

    Corriger le niveau antérieur (vers une valeur) sans dire la qualité la
    recalcule, comme à la création : la laisser telle quelle ferait mentir la
    fiche dès qu'on corrige une saisie. Effacer le niveau ne la touche pas.
    Une qualité envoyée l'emporte toujours.
    """
    sent = _sent_fields(data)
    targets: dict[str, object] = {name: getattr(data, name) for name in sent}
    # Un niveau effacé ne dit rien de la qualité : elle reste telle quelle,
    # pour ne pas perdre en silence une valeur posée à la main.
    if "previous_level" in sent and data.previous_level is not None and "is_repeater" not in sent:
        targets["is_repeater"] = repeater_status(data.previous_level, class_code)
    return targets


async def _apply(
    db: AsyncSession,
    enrollment: Enrollment,
    data: EnrollmentProfileUpdate,
    actor: int,
    class_code: PreviousLevel | None,
) -> None:
    """Écrit les champs et journalise ceux qui changent vraiment, qualité recalculée comprise."""
    targets = _targets(data, class_code)
    new_values = {name: _plain(value) for name, value in targets.items()}
    old_values = {name: _plain(getattr(enrollment, name)) for name in targets}
    changed = {name for name in targets if old_values[name] != new_values[name]}
    for name, value in targets.items():
        setattr(enrollment, name, value)
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
    level_name = await level_name_of_class(db, enrollment.class_id)
    if "lv2" in data.model_fields_set:
        ensure_lv2_allowed(level_name, data.lv2)

    async with db.begin_nested():
        await _apply(db, enrollment, data, updated_by, national_level_code(level_name))
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


def _class_code(enrollment: Enrollment) -> PreviousLevel | None:
    """Le code national de la classe, sur un lot dont le niveau est déjà chargé."""
    level = enrollment.class_.level
    return national_level_code(level.name if level else None)


def _check_batch(request: EnrollmentProfileBatchRequest, found: dict[int, Enrollment]) -> None:
    """Refuse le lot entier, en nommant chaque inscription fautive."""
    missing = sorted(i.enrollment_id for i in request.items if i.enrollment_id not in found)
    if missing:
        raise BusinessValidationError(
            f"Inscriptions introuvables, aucune fiche n'a été modifiée : {missing}"
        )
    lv2_refused: list[int] = []
    for item in request.items:
        code = _class_code(found[item.enrollment_id])
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
            enrollment = found[item.enrollment_id]
            await _apply(db, enrollment, item, updated_by, _class_code(enrollment))
    await db.commit()
    return {"updated": len(request.items)}
