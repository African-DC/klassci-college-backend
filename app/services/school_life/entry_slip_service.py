"""Billet d'entrée — réadmission en cours après une absence régularisée.

Le billet ne raconte pas une absence, il en ferme une. Il part d'un
enregistrement déjà saisi dans le cahier d'appel et le bascule en « excusé » :
c'est ce qui garantit que le taux d'assiduité affiché en conseil de classe et
le papier que l'élève tend à son professeur disent la même chose.

**Deux temps, et l'ordre compte.** `compose()` vérifie et prépare, sans rien
écrire. `close_absence()` bascule le cahier d'appel et valide. Entre les deux,
l'appelant fabrique le PDF : le cahier ne bouge qu'une fois le papier
imprimable en main. Faire l'inverse — régulariser puis tenter le rendu —
laissait, chaque fois que la fabrication du PDF échouait, une absence excusée
sans billet, que plus personne ne pouvait rouvrir.

**Réimprimer est permis.** Un billet se perd, une imprimante bourre. Sur un
enregistrement déjà régularisé, le service refabrique le papier et n'écrit
rien : il n'y a pas de seconde régularisation à craindre puisqu'il n'y a pas
de seconde écriture.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.audit import AuditAction, audit_log
from app.core.exceptions import BusinessValidationError, NotFoundError
from app.models.attendance import AttendanceRecord, AttendanceStatus
from app.services.school_life._common import load_student_context

# Un billet d'entrée ne se délivre que sur une absence ou un retard. Sur un
# élève noté présent, il n'aurait rien à régulariser.
_CLOSEABLE_STATUSES = {AttendanceStatus.ABSENT.value, AttendanceStatus.LATE.value}

#: Déjà régularisé par un billet : on réimprime, on ne rerégularise pas.
_REPRINTABLE_STATUSES = {AttendanceStatus.EXCUSED.value}


@dataclass(frozen=True, slots=True)
class EntrySlip:
    """Un billet prêt à imprimer, et ce qu'il reste à inscrire au cahier d'appel."""

    payload: dict[str, Any]
    record: AttendanceRecord
    previous_status: str
    previous_notes: str | None
    justification: str
    #: L'absence était déjà régularisée : c'est une réimpression, rien à écrire.
    reprint: bool


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


async def compose(
    db: AsyncSession,
    record_id: int,
    *,
    resume_date: date | None,
    notes: str | None,
) -> EntrySlip:
    """Vérifie l'appel visé et prépare le billet, sans rien écrire."""
    record = await _load_record(db, record_id)
    current_status = record.status.value if hasattr(record.status, "value") else record.status
    reprint = current_status in _REPRINTABLE_STATUSES
    if not reprint and current_status not in _CLOSEABLE_STATUSES:
        raise BusinessValidationError(
            "Ce billet ne peut être délivré que sur une absence ou un retard. "
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

    # La note reste courte et lisible dans le cahier d'appel : c'est elle que
    # l'éducateur relit six mois plus tard pour se rappeler pourquoi la journée
    # a basculé en « excusé ».
    justification = f"Régularisée par billet d'entrée du {issued_at.strftime('%d/%m/%Y')}"
    if notes:
        justification = f"{justification} — {notes}"
    justification = justification[:255]

    payload = {
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
    return EntrySlip(
        payload=payload,
        record=record,
        previous_status=current_status,
        previous_notes=record.notes,
        justification=justification,
        reprint=reprint,
    )


async def close_absence(db: AsyncSession, slip: EntrySlip, *, actor_id: int) -> None:
    """Bascule l'appel en « excusé ». À n'appeler qu'une fois le billet produit.

    Sur une réimpression, il n'y a rien à écrire : l'appel est déjà régularisé
    et la note d'origine doit rester telle quelle.
    """
    if slip.reprint:
        return

    record = slip.record
    record.status = AttendanceStatus.EXCUSED
    record.notes = slip.justification

    await audit_log(
        db,
        entity_type="attendance_record",
        entity_id=record.id,
        action=AuditAction.UPDATE,
        user_id=actor_id,
        # La note d'origine part au journal avant d'être remplacée : « parti à
        # l'infirmerie » est une observation de terrain, et la perdre sans
        # trace enlèverait à l'éducateur la seule copie qui en restait.
        old_values={"status": slip.previous_status, "notes": slip.previous_notes},
        new_values={"status": AttendanceStatus.EXCUSED.value, "notes": record.notes},
    )
    await db.commit()
