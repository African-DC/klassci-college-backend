"""Billet d'entrée — réadmission en cours après une absence régularisée.

Le billet ne raconte pas une absence, il en ferme une. Il part d'un
enregistrement déjà saisi dans le cahier d'appel et le bascule en « excusé » :
c'est ce qui garantit que le taux d'assiduité affiché en conseil de classe et
le papier que l'élève tend à son professeur disent la même chose.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.audit import AuditAction, audit_log
from app.core.exceptions import BusinessValidationError, NotFoundError
from app.models.attendance import AttendanceRecord, AttendanceStatus
from app.services.school_life._common import load_student_context

# Un billet d'entrée ne se délivre que sur une absence ouverte. Sur un élève
# noté présent, il n'aurait rien à régulariser ; sur une absence déjà excusée,
# il ferait croire à une seconde régularisation de la même journée.
_CLOSEABLE_STATUSES = {AttendanceStatus.ABSENT.value, AttendanceStatus.LATE.value}


async def _load_record(db: AsyncSession, record_id: int) -> AttendanceRecord:
    stmt = (
        select(AttendanceRecord)
        .where(AttendanceRecord.id == record_id)
        .options(selectinload(AttendanceRecord.context))
    )
    record = (await db.execute(stmt)).scalar_one_or_none()
    if record is None:
        raise NotFoundError("AttendanceRecord", record_id)
    return record


async def close_absence_and_compose(
    db: AsyncSession,
    record_id: int,
    *,
    resume_date: date | None,
    notes: str | None,
    actor_id: int,
) -> dict[str, Any]:
    """Ferme l'absence visée et renvoie de quoi imprimer le billet."""
    record = await _load_record(db, record_id)
    current_status = record.status.value if hasattr(record.status, "value") else record.status
    if current_status not in _CLOSEABLE_STATUSES:
        raise BusinessValidationError(
            "Ce billet ne peut être délivré que sur une absence ou un retard non régularisé. "
            "L'appel enregistré pour cette séance ne relève ni de l'un ni de l'autre."
        )

    absence_date = record.context.date if record.context else None
    effective_resume = resume_date or date.today()
    if absence_date is not None and effective_resume < absence_date:
        raise BusinessValidationError(
            "La reprise des cours ne peut pas précéder l'absence qu'elle régularise."
        )

    context = await load_student_context(db, record.student_id)
    issued_at = datetime.utcnow()

    record.status = AttendanceStatus.EXCUSED
    # La note reste courte et lisible dans le cahier d'appel : c'est elle que
    # l'éducateur relit six mois plus tard pour se rappeler pourquoi la journée
    # a basculé en « excusé ».
    justification = f"Régularisée par billet d'entrée du {issued_at.strftime('%d/%m/%Y')}"
    if notes:
        justification = f"{justification} — {notes}"
    record.notes = justification[:255]

    await audit_log(
        db,
        entity_type="attendance_record",
        entity_id=record.id,
        action=AuditAction.UPDATE,
        user_id=actor_id,
        old_values={"status": current_status},
        new_values={"status": AttendanceStatus.EXCUSED.value, "notes": record.notes},
    )
    await db.commit()

    return {
        "student": context.student_payload(),
        "student_last_name": context.student.last_name,
        "class_name": context.class_name,
        "academic_year_name": context.academic_year_name,
        "school_settings": context.school_settings,
        "absence_date": absence_date,
        "resume_date": effective_resume,
        "issued_at": issued_at,
        # Pièce interne : pas de sceau numérique, une référence lisible suffit
        # à retrouver l'appel exact dans le cahier.
        "reference": f"BE-{issued_at.year}-{record.id}",
    }
