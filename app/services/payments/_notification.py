"""Notification dispatcher pour les évènements paiement — best-effort.

Isolé pour ne pas polluer la logique métier core. Toute exception est
loggée et silencieusement ignorée (la notif ne doit jamais bloquer
l'enregistrement comptable).
"""

from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fee import Payment
from app.services.payments._state import logger


async def dispatch_payment_notification(
    db: AsyncSession, payment: Payment, *, kind: Literal["received", "validated"]
) -> None:
    """Notifie l'élève du paiement reçu ou validé. Best-effort."""
    try:
        from app.models.notification import NotificationType
        from app.services import notification_dispatch_service as notif

        enrollment = getattr(payment, "enrollment", None)
        if enrollment is None:
            return
        student = getattr(enrollment, "student", None)
        if student is None or not getattr(student, "user_id", None):
            return

        title = "Paiement reçu" if kind == "received" else "Paiement validé"
        verb = "enregistré" if kind == "received" else "validé"
        body = f"Votre paiement de {payment.amount} FCFA a été {verb}."

        await notif.dispatch_notification(
            db,
            user_id=student.user_id,
            notification_type=NotificationType.PAYMENT_RECEIVED,
            context={
                "title": title,
                "body": body,
                "amount": str(payment.amount),
            },
        )

        # Notification parents via MailPulse (email + WhatsApp) — best-effort,
        # gardée par la config tenant (désactivée par défaut).
        from app.services.mailpulse import workflow_service as mp_workflow

        parent_body = f"Un versement de {payment.amount} FCFA a été {verb} pour votre enfant."
        await mp_workflow.notify_student_parents(
            db,
            student_id=student.id,
            event=mp_workflow.EVENT_PAYMENT,
            subject=title,
            body=parent_body,
            external_event_id=f"payment-{payment.id}",
        )
    except Exception:
        logger.exception("Failed to dispatch payment notification (kind=%s)", kind)
