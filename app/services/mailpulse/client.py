"""Client HTTP MailPulse — contacts + messages (email / WhatsApp).

Best-effort et défensif : ne lève jamais pour une erreur réseau ou un refus
métier MailPulse. Toute tentative renvoie un ``MailPulseResult`` que l'appelant
inspecte. La clé API n'est JAMAIS loggée.

Contrat API (mailpulse-two.vercel.app) :
- ``POST {base}/api/v1/contacts`` — upsert contact (email|phone|external_id).
- ``POST {base}/api/v1/messages`` — envoi (channel email|whatsapp, recipient,
  content text|template). Codes d'erreur métier connus renvoyés en 422.
"""

import logging
import unicodedata
from dataclasses import dataclass
from typing import Any, Literal

import httpx

logger = logging.getLogger("mailpulse")

Channel = Literal["email", "whatsapp"]

# Codes d'erreur métier documentés côté MailPulse (renvoyés en 422).
ERROR_TEMPLATE_REQUIRED = "whatsapp_template_required"
ERROR_TEMPLATE_NOT_APPROVED = "template_not_approved"
ERROR_CHANNEL_NOT_CONFIGURED = "channel_not_configured"
ERROR_PROVIDER = "provider_error"

# Messages utilisateur (français) mappés sur les codes techniques.
_ERROR_MESSAGES = {
    ERROR_TEMPLATE_REQUIRED: (
        "WhatsApp exige un template approuvé hors de la fenêtre de 24h. "
        "Configurez le template côté Meta / MailPulse."
    ),
    ERROR_TEMPLATE_NOT_APPROVED: (
        "Le template WhatsApp référencé n'est pas encore approuvé par Meta."
    ),
    ERROR_CHANNEL_NOT_CONFIGURED: (
        "Le canal (email ou WhatsApp) n'est pas branché dans MailPulse."
    ),
    ERROR_PROVIDER: "Le fournisseur (email ou WhatsApp) a renvoyé une erreur.",
}


def humanize_error(code: str | None) -> str:
    """Message français lisible pour un code d'erreur MailPulse."""
    if not code:
        return "Envoi refusé par MailPulse."
    return _ERROR_MESSAGES.get(code, f"Envoi refusé par MailPulse ({code}).")


@dataclass(slots=True)
class MailPulseResult:
    """Résultat d'un appel MailPulse — jamais une exception côté appelant."""

    ok: bool
    status: str  # queued | sent | delivered | failed | dry_run | error
    error_code: str | None = None
    error_message: str | None = None
    message_id: str | None = None
    contact_id: str | None = None

    @classmethod
    def dry_run(cls) -> "MailPulseResult":
        return cls(ok=True, status="dry_run")

    @classmethod
    def transport_error(cls, message: str) -> "MailPulseResult":
        return cls(ok=False, status="error", error_message=message)


def normalize_phone_e164(raw: str, *, default_country: str = "225") -> str | None:
    """Normalise un numéro ivoirien (ou déjà E.164) au format ``+225XXXXXXXXXX``.

    MailPulse renormalise de son côté ; on envoie déjà propre pour limiter les
    rejets. Retourne ``None`` si le numéro est manifestement invalide.
    """
    if not raw:
        return None
    txt = "".join(ch for ch in raw.strip() if ch.isdigit() or ch == "+")
    if txt.startswith("+"):
        digits = txt[1:]
        return f"+{digits}" if len(digits) >= 8 else None
    if txt.startswith("00"):
        digits = txt[2:]
        return f"+{digits}" if len(digits) >= 8 else None
    digits = txt
    if len(digits) < 8:
        return None
    if digits.startswith(default_country):
        return f"+{digits}"
    return f"+{default_country}{digits}"


class MailPulseClient:
    """Client MailPulse minimaliste (contacts + messages)."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        timeout: int = 20,
        contacts_endpoint: str = "/api/v1/contacts",
        messages_endpoint: str = "/api/v1/messages",
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._contacts_endpoint = contacts_endpoint
        self._messages_endpoint = messages_endpoint

    @property
    def configured(self) -> bool:
        return bool(self._api_key and self._base_url)

    def _headers(self, idempotency_key: str | None = None) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        if idempotency_key:
            headers["idempotency-key"] = idempotency_key
        return headers

    async def upsert_contact(
        self,
        *,
        email: str | None = None,
        phone: str | None = None,
        external_id: str | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
        language: str = "fr",
    ) -> MailPulseResult:
        payload: dict[str, Any] = {"language": language, "subscribed": True}
        if email:
            payload["email"] = email
        if phone:
            payload["phone"] = phone
        if external_id:
            payload["external_id"] = external_id
        if first_name:
            payload["first_name"] = first_name
        if last_name:
            payload["last_name"] = last_name
        return await self._post(self._contacts_endpoint, payload, operation="contact_upsert")

    async def send_message(
        self,
        *,
        channel: Channel,
        recipient: str,
        body: str,
        subject: str | None = None,
        sender_email: str | None = None,
        sender_name: str | None = None,
        idempotency_key: str | None = None,
        external_event_id: str | None = None,
    ) -> MailPulseResult:
        recipient_type = "email" if channel == "email" else "phone"
        value = recipient
        if channel == "whatsapp":
            normalized = normalize_phone_e164(recipient)
            if normalized is None:
                return MailPulseResult(
                    ok=False, status="error", error_message="Numéro WhatsApp invalide."
                )
            value = normalized

        metadata: dict[str, Any] = {}
        if subject:
            metadata["subject"] = subject
        if sender_email:
            metadata["sender_email"] = sender_email
        if sender_name:
            metadata["sender_name"] = sender_name
        if external_event_id:
            metadata["external_event_id"] = external_event_id

        payload: dict[str, Any] = {
            "channel": channel,
            "recipient": {"type": recipient_type, "value": value},
            "content": {"type": "text", "text": _sanitize(body)},
        }
        if metadata:
            payload["metadata"] = metadata

        return await self._post(
            self._messages_endpoint,
            payload,
            operation=f"{channel}_send",
            idempotency_key=idempotency_key,
        )

    async def _post(
        self,
        endpoint: str,
        payload: dict[str, Any],
        *,
        operation: str,
        idempotency_key: str | None = None,
    ) -> MailPulseResult:
        url = f"{self._base_url}{endpoint}"
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    url, json=payload, headers=self._headers(idempotency_key)
                )
        except httpx.HTTPError as exc:
            # Jamais de clé API dans le log — uniquement l'opération et l'erreur.
            logger.warning(
                "MailPulse %s transport error: %s", operation, exc.__class__.__name__
            )
            return MailPulseResult.transport_error("MailPulse injoignable.")

        return _parse_response(resp, operation=operation)


def _sanitize(text: str) -> str:
    """Retire les caractères de contrôle qui font échouer certains providers."""
    return "".join(ch for ch in text if ch == "\n" or unicodedata.category(ch)[0] != "C")


def _parse_response(resp: httpx.Response, *, operation: str) -> MailPulseResult:
    try:
        data = resp.json()
    except ValueError:
        data = {}

    if resp.status_code in (200, 201, 202):
        message = data.get("message") or {}
        contact = data.get("contact") or {}
        status = message.get("status") or "queued"
        return MailPulseResult(
            ok=True,
            status=status,
            message_id=message.get("id"),
            contact_id=contact.get("id"),
        )

    # 422 = refus métier (template requis, canal non configuré, provider...).
    message = data.get("message") or {}
    code = data.get("code") or message.get("error_code")
    logger.info("MailPulse %s rejected: status=%s code=%s", operation, resp.status_code, code)
    return MailPulseResult(
        ok=False,
        status="failed",
        error_code=code,
        error_message=humanize_error(code),
        message_id=message.get("id"),
    )
