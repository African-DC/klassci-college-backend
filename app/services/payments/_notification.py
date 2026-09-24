"""Prévenir après un versement : l'élève tout de suite, les parents après.

Deux vitesses, et c'est tout l'objet de ce module.

- La notification dans l'application est une ligne en base : elle s'écrit en
  quelques millisecondes, pendant la requête.
- Le message aux parents passe par MailPulse : jusqu'à trois appels HTTP par
  parent (contact, e-mail, WhatsApp), vingt secondes de délai chacun. Tant
  qu'il partait pendant la requête, l'écran de la caissière restait figé sur
  un versement pourtant déjà écrit ; elle appuyait de nouveau, et la caisse
  enregistrait un second billet. Il part désormais une fois la réponse rendue,
  dans sa propre session : celle de la requête est fermée à ce moment-là.

Tout est best-effort : une notification ne bloque jamais un encaissement, et
son échec est journalisé, jamais avalé.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.money import fcfa
from app.models.fee import Payment
from app.services.payments._state import logger

Kind = Literal["received", "validated"]

#: Ce qui reçoit l'envoi différé : `BackgroundTasks.add_task` dans une requête.
Differer = Callable[..., None]


@dataclass(frozen=True, slots=True)
class ParentMessage:
    """Le message aux parents, sans rien qui dépende de la session d'origine."""

    student_id: int
    subject: str
    body: str
    external_event_id: str


def _verbe(kind: Kind) -> tuple[str, str]:
    return ("Paiement reçu", "enregistré") if kind == "received" else ("Paiement validé", "validé")


def parent_message(payment: Payment, kind: Kind) -> ParentMessage | None:
    """Le message à envoyer aux parents, ou `None` si l'élève est introuvable."""
    student = getattr(getattr(payment, "enrollment", None), "student", None)
    if student is None:
        return None
    title, verbe = _verbe(kind)
    return ParentMessage(
        student_id=student.id,
        subject=title,
        body=f"Un versement de {fcfa(payment.amount)} a été {verbe} pour votre enfant.",
        external_event_id=f"payment-{payment.id}",
    )


async def send_parent_message(db: AsyncSession, message: ParentMessage) -> None:
    """Envoie le message aux parents via MailPulse, gardé par la config école."""
    from app.services.mailpulse import workflow_service as mp_workflow

    await mp_workflow.notify_student_parents(
        db,
        student_id=message.student_id,
        event=mp_workflow.EVENT_PAYMENT,
        subject=message.subject,
        body=message.body,
        external_event_id=message.external_event_id,
    )


async def send_parent_message_later(tenant_id: str, message: ParentMessage) -> None:
    """L'envoi aux parents, une fois la réponse rendue, dans sa propre session."""
    from app.core.database import _get_session_factory

    try:
        factory = await _get_session_factory(tenant_id)
        async with factory() as db:
            await send_parent_message(db, message)
    except Exception:
        logger.exception("Message parents du versement %s non envoye", message.external_event_id)


async def notify_student_in_app(db: AsyncSession, payment: Payment, kind: Kind) -> None:
    """La notification de l'élève dans l'application. Rapide, faite sur place."""
    try:
        from app.models.notification import NotificationType
        from app.services import notification_dispatch_service as notif

        student = getattr(getattr(payment, "enrollment", None), "student", None)
        if student is None or not getattr(student, "user_id", None):
            return
        title, verbe = _verbe(kind)
        await notif.dispatch_notification(
            db,
            user_id=student.user_id,
            notification_type=NotificationType.PAYMENT_RECEIVED,
            context={
                "title": title,
                "body": f"Votre paiement de {fcfa(payment.amount)} a été {verbe}.",
                "amount": str(payment.amount),
            },
        )
        # `dispatch_notification` ne fait que `flush` : sans ce commit, la
        # fermeture de la session annulerait la notification sans bruit.
        await db.commit()
    except Exception:
        logger.exception("Notification eleve du versement %s echouee", payment.id)
        # Une session en echec refuserait tout ce qui suit, et la notification
        # du createur et des valideurs se perdrait a son tour sans bruit.
        await db.rollback()


async def dispatch_payment_notification(
    db: AsyncSession,
    payment: Payment,
    *,
    kind: Kind,
    differer: Differer | None = None,
    tenant_id: str | None = None,
) -> None:
    """Notifie l'élève, puis les parents.

    Avec `differer` et `tenant_id`, le message aux parents part après la
    réponse. Sans eux (ligne de commande, jeu de démonstration), il part sur
    place, comme avant.
    """
    await notify_student_in_app(db, payment, kind)
    message = parent_message(payment, kind)
    if message is None:
        return
    if differer is not None and tenant_id is not None:
        differer(send_parent_message_later, tenant_id, message)
        return
    try:
        await send_parent_message(db, message)
    except Exception:
        logger.exception("Message parents du versement %s echoue", payment.id)
