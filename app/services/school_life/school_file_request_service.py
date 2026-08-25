"""Demande de dossier scolaire — courrier vers l'établissement d'origine."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditAction, audit_log
from app.services.school_life._common import issue_act_seal, load_student_context

DOCUMENT_TYPE = "demande_dossier_scolaire"


async def compose_request_data(
    db: AsyncSession, student_id: int, *, actor_id: int
) -> dict[str, Any]:
    """Prépare la demande, scelle l'émission et trace le courrier.

    Le sceau est posé avant le rendu : le document part vers un autre
    établissement, qui doit pouvoir vérifier en ligne que la demande vient
    bien du collège et n'a pas été fabriquée par la famille.
    """
    context = await load_student_context(db, student_id)
    issued_at = datetime.utcnow()

    source_data = {
        "student": context.student_payload(),
        "class_name": context.class_name,
        "academic_year_name": context.academic_year_name,
        "school_settings": context.school_settings,
    }
    verification = await issue_act_seal(
        db,
        document_type=DOCUMENT_TYPE,
        ref_prefix="DDS",
        context=context,
        issued_at=issued_at,
        source_data=source_data,
        # La demande n'a pas de registre : une émission corrigée doit bien
        # remplacer la précédente, l'ancien courrier n'ayant plus cours.
        act_id=None,
    )

    await audit_log(
        db,
        entity_type="school_file_request",
        entity_id=student_id,
        action=AuditAction.CREATE,
        user_id=actor_id,
        new_values={
            "reference": verification["reference"],
            "previous_school": context.student.previous_school,
        },
    )
    await db.commit()

    return {
        **source_data,
        "issued_at": issued_at,
        "reference": verification["reference"],
        "verification": verification,
        "school_settings": context.school_settings,
        "student_last_name": context.student.last_name,
    }
