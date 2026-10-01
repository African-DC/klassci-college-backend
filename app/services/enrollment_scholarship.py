"""La bourse d'une inscription : une au plus, posée, remplacée ou retirée.

La fiche de renseignements n'a qu'une case « régime » (boursier ou non). Un
index unique sur `scholarships.enrollment_id` tient la règle en base ; ce
service la tient en écriture, en remplaçant la bourse existante plutôt que
d'en empiler une seconde.

Chaque geste est journalisé sur l'inscription : c'est elle que l'écran du
journal nomme, et c'est d'elle qu'on parle quand une famille conteste.
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.archive_filter import INCLUDE_ARCHIVED
from app.core.audit import AuditAction, audit_log
from app.core.exceptions import BusinessValidationError, ConflictError, NotFoundError
from app.models.deep_report import Scholarship
from app.models.enrollment import Enrollment, is_closed
from app.schemas.enrollment_profile import ScholarshipSummary, ScholarshipUpsert

CLOSED_ENROLLMENT_MESSAGE = (
    "Cette inscription est refusée, annulée ou à la corbeille : on ne peut pas lui "
    "accorder de bourse."
)
CONCURRENT_WRITE_MESSAGE = (
    "La bourse de cette inscription vient d'être modifiée par quelqu'un d'autre. "
    "Rechargez la fiche puis recommencez."
)

_AUDITED = ("kind", "provider", "decision_number", "amount", "granted_on")


def _snapshot(scholarship: Scholarship) -> dict[str, Any]:
    """La bourse telle que le journal JSON peut la garder."""
    values: dict[str, Any] = {}
    for name in _AUDITED:
        value = getattr(scholarship, name)
        values[name] = str(getattr(value, "value", value)) if value is not None else None
    return values


async def _ensure_enrollment(db: AsyncSession, enrollment_id: int) -> Enrollment:
    # La corbeille est lue aussi : une inscription archivée doit répondre
    # « dossier fermé » (422), pas « introuvable ».
    stmt = (
        select(Enrollment)
        .where(Enrollment.id == enrollment_id)
        .execution_options(**{INCLUDE_ARCHIVED: True})
    )
    enrollment = (await db.execute(stmt)).scalar_one_or_none()
    if enrollment is None:
        raise NotFoundError("Enrollment", enrollment_id)
    return enrollment


def _ensure_open(enrollment: Enrollment) -> None:
    """Pas de bourse sur un dossier refusé, annulé ou à la corbeille : l'élève n'est pas là."""
    if is_closed(enrollment.status) or enrollment.archived_at is not None:
        raise BusinessValidationError(CLOSED_ENROLLMENT_MESSAGE)


async def _current(db: AsyncSession, enrollment_id: int) -> Scholarship | None:
    stmt = select(Scholarship).where(Scholarship.enrollment_id == enrollment_id)
    return (await db.execute(stmt)).scalar_one_or_none()


async def _audit(
    db: AsyncSession,
    enrollment_id: int,
    actor: int,
    old: dict[str, Any] | None,
    new: dict[str, Any] | None,
) -> None:
    await audit_log(
        db,
        entity_type="enrollment",
        action=AuditAction.UPDATE,
        user_id=actor,
        entity_id=enrollment_id,
        old_values={"scholarship": old},
        new_values={"scholarship": new},
    )


async def _write(db: AsyncSession, enrollment_id: int, data: ScholarshipUpsert, actor: int) -> None:
    """Une tentative d'écriture, dans son propre point de sauvegarde."""
    async with db.begin_nested():
        scholarship = await _current(db, enrollment_id)
        old = _snapshot(scholarship) if scholarship is not None else None
        if scholarship is None:
            scholarship = Scholarship(enrollment_id=enrollment_id)
            db.add(scholarship)
        for name, value in data.model_dump().items():
            setattr(scholarship, name, value)
        await db.flush()
        await _audit(db, enrollment_id, actor, old, _snapshot(scholarship))


async def upsert_scholarship(
    db: AsyncSession, enrollment_id: int, data: ScholarshipUpsert, *, actor: int
) -> ScholarshipSummary:
    """Pose la bourse, ou remplace celle qui existe (PUT : le corps fait foi).

    Deux guichets qui posent la bourse au même instant : le second bute sur
    l'index unique. On rejoue alors une fois, et la seconde lecture trouve la
    bourse du premier, qu'elle remplace. Un second échec rend un 409.
    """
    _ensure_open(await _ensure_enrollment(db, enrollment_id))
    for attempt in range(2):
        try:
            await _write(db, enrollment_id, data, actor)
            break
        except IntegrityError as exc:
            if attempt == 1:
                raise ConflictError(CONCURRENT_WRITE_MESSAGE) from exc
    await db.commit()
    return ScholarshipSummary(
        kind=data.kind, provider=data.provider, decision_number=data.decision_number
    )


async def delete_scholarship(db: AsyncSession, enrollment_id: int, *, actor: int) -> None:
    """Retire la bourse. Sans bourse, il n'y a rien à faire ni à journaliser."""
    await _ensure_enrollment(db, enrollment_id)
    scholarship = await _current(db, enrollment_id)
    if scholarship is None:
        return
    async with db.begin_nested():
        old = _snapshot(scholarship)
        await db.delete(scholarship)
        await db.flush()
        await _audit(db, enrollment_id, actor, old, None)
    await db.commit()
