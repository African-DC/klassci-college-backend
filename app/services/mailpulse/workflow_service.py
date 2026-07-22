"""Workflows MailPulse réels — notifient les parents lors d'évènements métier.

Best-effort et doublement gardés : rien n'est envoyé tant que le tenant n'a pas
activé MailPulse ET les workflows réels (``mailpulse_real_workflows_enabled``),
et que le type d'évènement n'est pas activé dans les paramètres de l'école.

Ne journalise que event / channel / status / parent_id / student_id — jamais
de secret ni de contenu sensible.
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.academic import SchoolSettings
from app.models.user import Parent, ParentStudent, Student
from app.services import admin_service
from app.services.mailpulse.client import MailPulseClient
from app.services.mailpulse.settings_service import build_client

logger = logging.getLogger("mailpulse")

EVENT_PAYMENT = "payment_received"
EVENT_ABSENCE = "absence_reported"
EVENT_GRADE = "grade_published"
EVENT_FEE_REMINDER = "fee_reminder"

# Chaque évènement est aussi gardé par l'interrupteur de type côté école.
_EVENT_SCHOOL_TOGGLE = {
    EVENT_PAYMENT: "notify_payments",
    EVENT_ABSENCE: "notify_absences",
    EVENT_GRADE: "notify_grades",
    EVENT_FEE_REMINDER: "notify_payments",
}


async def _get_student_parents(db: AsyncSession, student_id: int) -> list[Parent]:
    stmt = (
        select(Student)
        .where(Student.id == student_id)
        .options(selectinload(Student.parents).selectinload(ParentStudent.parent))
    )
    student = (await db.execute(stmt)).scalar_one_or_none()
    if student is None:
        return [ps.parent for ps in [] if ps.parent]
    return [ps.parent for ps in student.parents if ps.parent]


async def _notify_parent(
    client: MailPulseClient,
    school: SchoolSettings,
    parent: Parent,
    *,
    event: str,
    subject: str,
    body: str,
    student_id: int,
    external_event_id: str | None,
) -> None:
    # Upsert du contact (best-effort — n'empêche pas l'envoi si échoue).
    await client.upsert_contact(
        email=parent.email,
        phone=parent.phone,
        external_id=f"parent-{parent.id}",
        first_name=parent.first_name,
        last_name=parent.last_name,
        language=school.mailpulse_default_language or "fr",
    )

    # Email : uniquement si l'école a activé le canal email.
    if parent.email and school.notify_by_email:
        result = await client.send_message(
            channel="email",
            recipient=parent.email,
            subject=subject,
            body=body,
            sender_email=school.mailpulse_sender_email,
            sender_name=school.mailpulse_sender_name,
            external_event_id=external_event_id,
        )
        logger.info(
            "mailpulse workflow event=%s channel=email status=%s parent_id=%s student_id=%s",
            event,
            result.status,
            parent.id,
            student_id,
        )

    # WhatsApp : dès que MailPulse est actif et que le parent a un numéro.
    if parent.phone:
        result = await client.send_message(
            channel="whatsapp",
            recipient=parent.phone,
            subject=subject,
            body=body,
            external_event_id=external_event_id,
        )
        logger.info(
            "mailpulse workflow event=%s channel=whatsapp status=%s parent_id=%s student_id=%s",
            event,
            result.status,
            parent.id,
            student_id,
        )


async def notify_student_parents(
    db: AsyncSession,
    *,
    student_id: int,
    event: str,
    subject: str,
    body: str,
    external_event_id: str | None = None,
) -> None:
    """Notifie les parents d'un élève pour un évènement. Best-effort, jamais bloquant."""
    try:
        school = await admin_service.get_school_settings(db)
        if not (school.mailpulse_enabled and school.mailpulse_real_workflows_enabled):
            return
        toggle = _EVENT_SCHOOL_TOGGLE.get(event)
        if toggle and not getattr(school, toggle, False):
            return
        client = build_client(school)
        if client is None:
            return
        parents = await _get_student_parents(db, student_id)
        for parent in parents:
            await _notify_parent(
                client,
                school,
                parent,
                event=event,
                subject=subject,
                body=body,
                student_id=student_id,
                external_event_id=external_event_id,
            )
    except Exception:
        logger.exception("mailpulse workflow %s failed for student %s", event, student_id)
