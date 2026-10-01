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
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditAction, audit_log
from app.core.exceptions import NotFoundError
from app.models.deep_report import Scholarship
from app.models.enrollment import Enrollment
from app.schemas.enrollment_profile import ScholarshipSummary, ScholarshipUpsert

_AUDITED = ("kind", "provider", "decision_number", "amount", "granted_on")


def _snapshot(scholarship: Scholarship) -> dict[str, Any]:
    """La bourse telle que le journal JSON peut la garder."""
    values: dict[str, Any] = {}
    for name in _AUDITED:
        value = getattr(scholarship, name)
        values[name] = str(getattr(value, "value", value)) if value is not None else None
    return values


async def _ensure_enrollment(db: AsyncSession, enrollment_id: int) -> None:
    stmt = select(Enrollment.id).where(Enrollment.id == enrollment_id)
    if (await db.execute(stmt)).scalar_one_or_none() is None:
        raise NotFoundError("Enrollment", enrollment_id)


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


async def upsert_scholarship(
    db: AsyncSession, enrollment_id: int, data: ScholarshipUpsert, *, actor: int
) -> ScholarshipSummary:
    """Pose la bourse, ou remplace celle qui existe (PUT : le corps fait foi)."""
    await _ensure_enrollment(db, enrollment_id)
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
