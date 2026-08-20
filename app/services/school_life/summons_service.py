"""Convocations de parents : émission, registre, suite donnée.

La convocation est le seul des quatre actes à vivre après son impression :
elle attend une réponse. Le registre existe pour répondre en conseil de classe
à « qui a été convoqué ce trimestre, et qui est venu ».
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.audit import AuditAction, audit_log
from app.core.exceptions import BusinessValidationError, NotFoundError
from app.models.school_life import ParentSummons, SummonsOutcome
from app.models.user import Parent
from app.schemas.school_life import (
    ParentSummonsCreate,
    ParentSummonsRegister,
    ParentSummonsResponse,
    SummonsOutcomeUpdate,
    SummonsRegisterSummary,
)
from app.services.school_life._common import (
    actor_name,
    current_class_names,
    issue_act_seal,
    load_student_context,
    resolve_trimester,
)

DOCUMENT_TYPE = "convocation_parent"

OUTCOME_LABELS_FR: dict[str, str] = {
    SummonsOutcome.PENDING.value: "Non renseigné",
    SummonsOutcome.ATTENDED.value: "Présent",
    SummonsOutcome.MISSED.value: "Absent",
}


async def _get_summons(db: AsyncSession, summons_id: int) -> ParentSummons:
    """Charge une convocation avec tout ce que la réponse et le PDF liront.

    Les relations sont préchargées ici parce que le service les parcourt après
    `commit()`, moment où SQLAlchemy a expiré les attributs.
    """
    stmt = (
        select(ParentSummons)
        .where(ParentSummons.id == summons_id)
        .options(
            selectinload(ParentSummons.student),
            selectinload(ParentSummons.parent),
            selectinload(ParentSummons.academic_year),
        )
    )
    summons = (await db.execute(stmt)).scalar_one_or_none()
    if summons is None:
        raise NotFoundError("ParentSummons", summons_id)
    return summons


def _to_response(
    summons: ParentSummons,
    *,
    class_name: str | None,
    issued_by_name: str | None,
) -> ParentSummonsResponse:
    student = summons.student
    parent_label = summons.parent_name
    if not parent_label and summons.parent is not None:
        parent_label = f"{summons.parent.first_name} {summons.parent.last_name}".strip()
    outcome = summons.outcome.value if hasattr(summons.outcome, "value") else summons.outcome
    return ParentSummonsResponse(
        id=summons.id,
        student_id=summons.student_id,
        student_name=f"{student.first_name} {student.last_name}".strip(),
        enrollment_number=student.enrollment_number,
        class_name=class_name,
        parent_id=summons.parent_id,
        parent_name=parent_label,
        academic_year_id=summons.academic_year_id,
        academic_year_name=summons.academic_year.name if summons.academic_year else None,
        trimester=summons.trimester,
        summons_date=summons.summons_date,
        summons_time=summons.summons_time,
        reason=summons.reason,
        reference=summons.reference,
        outcome=outcome,
        outcome_label=OUTCOME_LABELS_FR.get(outcome, outcome),
        outcome_notes=summons.outcome_notes,
        outcome_recorded_at=summons.outcome_recorded_at,
        issued_by_user_id=summons.issued_by_user_id,
        issued_by_name=issued_by_name,
        created_at=summons.created_at,
    )


async def create_summons(
    db: AsyncSession, data: ParentSummonsCreate, *, actor_id: int
) -> ParentSummonsResponse:
    """Enregistre une convocation et la rend imprimable."""
    context = await load_student_context(db, data.student_id)

    parent_name = data.parent_name
    if data.parent_id is not None:
        parent = await db.get(Parent, data.parent_id)
        if parent is None:
            raise NotFoundError("Parent", data.parent_id)
        parent_name = parent_name or f"{parent.first_name} {parent.last_name}".strip()

    trimester = data.trimester or await resolve_trimester(
        db, context.academic_year_id, data.summons_date
    )

    summons = ParentSummons(
        student_id=data.student_id,
        parent_id=data.parent_id,
        parent_name=parent_name,
        academic_year_id=context.academic_year_id,
        trimester=trimester,
        summons_date=data.summons_date,
        summons_time=data.summons_time,
        reason=data.reason,
        issued_by_user_id=actor_id,
        outcome=SummonsOutcome.PENDING,
    )
    db.add(summons)
    await db.flush()

    await audit_log(
        db,
        entity_type="parent_summons",
        entity_id=summons.id,
        action=AuditAction.CREATE,
        user_id=actor_id,
        new_values={
            "student_id": data.student_id,
            "summons_date": data.summons_date.isoformat(),
            "trimester": trimester,
        },
    )
    await db.commit()

    refreshed = await _get_summons(db, summons.id)
    return _to_response(
        refreshed,
        class_name=context.class_name,
        issued_by_name=await actor_name(db, actor_id),
    )


async def list_register(
    db: AsyncSession,
    *,
    academic_year_id: int | None = None,
    trimester: int | None = None,
    student_id: int | None = None,
    outcome: str | None = None,
) -> ParentSummonsRegister:
    """Registre des convocations, avec le décompte des suites données."""
    stmt = (
        select(ParentSummons)
        .options(
            selectinload(ParentSummons.student),
            selectinload(ParentSummons.parent),
            selectinload(ParentSummons.academic_year),
        )
        .order_by(ParentSummons.summons_date.desc(), ParentSummons.id.desc())
    )
    if academic_year_id is not None:
        stmt = stmt.where(ParentSummons.academic_year_id == academic_year_id)
    if trimester is not None:
        stmt = stmt.where(ParentSummons.trimester == trimester)
    if student_id is not None:
        stmt = stmt.where(ParentSummons.student_id == student_id)
    if outcome is not None:
        stmt = stmt.where(ParentSummons.outcome == outcome)

    rows = list((await db.execute(stmt)).scalars().all())
    class_names = await current_class_names(db, {row.student_id for row in rows})
    issuer_ids = {row.issued_by_user_id for row in rows}
    issuers = {uid: await actor_name(db, uid) for uid in issuer_ids}

    items = [
        _to_response(
            row,
            class_name=class_names.get(row.student_id),
            issued_by_name=issuers.get(row.issued_by_user_id),
        )
        for row in rows
    ]
    return ParentSummonsRegister(
        items=items,
        summary=SummonsRegisterSummary(
            total=len(items),
            attended=sum(1 for i in items if i.outcome == SummonsOutcome.ATTENDED.value),
            missed=sum(1 for i in items if i.outcome == SummonsOutcome.MISSED.value),
            pending=sum(1 for i in items if i.outcome == SummonsOutcome.PENDING.value),
        ),
    )


async def get_summons(db: AsyncSession, summons_id: int) -> ParentSummonsResponse:
    summons = await _get_summons(db, summons_id)
    class_names = await current_class_names(db, {summons.student_id})
    return _to_response(
        summons,
        class_name=class_names.get(summons.student_id),
        issued_by_name=await actor_name(db, summons.issued_by_user_id),
    )


async def record_outcome(
    db: AsyncSession, summons_id: int, data: SummonsOutcomeUpdate, *, actor_id: int
) -> ParentSummonsResponse:
    """Note si le tuteur s'est présenté, une fois le rendez-vous passé."""
    summons = await _get_summons(db, summons_id)
    if summons.summons_date > date.today():
        raise BusinessValidationError(
            "La suite d'une convocation se renseigne à partir du jour du rendez-vous."
        )

    previous = summons.outcome.value if hasattr(summons.outcome, "value") else summons.outcome
    summons.outcome = SummonsOutcome(data.outcome)
    summons.outcome_notes = data.notes
    summons.outcome_recorded_by_user_id = actor_id
    summons.outcome_recorded_at = datetime.utcnow()

    await audit_log(
        db,
        entity_type="parent_summons",
        entity_id=summons.id,
        action=AuditAction.UPDATE,
        user_id=actor_id,
        old_values={"outcome": previous},
        new_values={"outcome": data.outcome},
    )
    await db.commit()

    refreshed = await _get_summons(db, summons_id)
    class_names = await current_class_names(db, {refreshed.student_id})
    return _to_response(
        refreshed,
        class_name=class_names.get(refreshed.student_id),
        issued_by_name=await actor_name(db, refreshed.issued_by_user_id),
    )


async def compose_document_data(db: AsyncSession, summons_id: int) -> dict[str, Any]:
    """Scelle la convocation et renvoie de quoi l'imprimer."""
    summons = await _get_summons(db, summons_id)
    context = await load_student_context(db, summons.student_id)
    issued_at = datetime.utcnow()

    parent_label = summons.parent_name
    if not parent_label and summons.parent is not None:
        parent_label = f"{summons.parent.first_name} {summons.parent.last_name}".strip()

    source_data: dict[str, Any] = {
        "student": context.student_payload(),
        "class_name": context.class_name,
        "academic_year_name": context.academic_year_name,
        "parent_name": parent_label,
        "summons_date": summons.summons_date,
        "summons_time": summons.summons_time,
        "reason": summons.reason,
        "school_settings": context.school_settings,
    }
    verification = await issue_act_seal(
        db,
        document_type=DOCUMENT_TYPE,
        ref_prefix="CVP",
        context=context,
        issued_at=issued_at,
        source_data=source_data,
    )
    # La référence rejoint le registre : le parent qui présente son papier au
    # guichet doit pouvoir être retrouvé sans fouiller les dates.
    summons.reference = verification["reference"]
    await db.commit()

    return {
        **source_data,
        "issued_at": issued_at,
        "reference": verification["reference"],
        "verification": verification,
        "school_settings": context.school_settings,
        "student_last_name": context.student.last_name,
    }
