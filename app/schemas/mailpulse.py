"""Schémas MailPulse — configuration tenant (get / update).

La clé API n'est JAMAIS renvoyée : la réponse expose seulement ``api_key_set``.
En update, une clé vide/absente conserve la clé existante.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

MailPulseEvent = Literal["payment_received", "absence_reported", "grade_published", "fee_reminder"]
MailPulseTestChannel = Literal["email", "whatsapp", "both"]


class MailPulseRecipient(BaseModel):
    """Destinataire de test avec interrupteur actif/inactif."""

    value: str
    enabled: bool = True

    @field_validator("value")
    @classmethod
    def strip_value(cls, v: str) -> str:
        return v.strip()


class MailPulseConfigResponse(BaseModel):
    """GET /admin/settings/mailpulse — sans la clé API en clair."""

    model_config = ConfigDict(from_attributes=True)

    enabled: bool = False
    base_url: str
    api_key_set: bool = False
    sender_email: str | None = None
    sender_name: str | None = None
    default_language: str = "fr"
    timeout: int = 20
    real_workflows_enabled: bool = False
    test_email_enabled: bool = True
    test_whatsapp_enabled: bool = True
    test_email_recipients: list[MailPulseRecipient] = []
    test_phone_recipients: list[MailPulseRecipient] = []
    inbound_secret_set: bool = False


class MailPulseConfigUpdate(BaseModel):
    """PUT /admin/settings/mailpulse — objet complet.

    ``api_key`` optionnel : ``None`` ou chaîne vide = conserver la clé actuelle.
    """

    enabled: bool
    base_url: str
    api_key: str | None = None
    sender_email: str | None = None
    sender_name: str | None = None
    default_language: str = "fr"
    timeout: int = 20
    real_workflows_enabled: bool
    test_email_enabled: bool
    test_whatsapp_enabled: bool
    test_email_recipients: list[MailPulseRecipient] = []
    test_phone_recipients: list[MailPulseRecipient] = []
    # Secret du webhook entrant (feature INFO) — write-only, vide = conservé.
    inbound_secret: str | None = None

    @field_validator("base_url")
    @classmethod
    def clean_base_url(cls, v: str) -> str:
        v = v.strip().rstrip("/")
        if v and not v.startswith(("http://", "https://")):
            raise ValueError("L'URL doit commencer par http:// ou https://")
        return v

    @field_validator("timeout")
    @classmethod
    def clamp_timeout(cls, v: int) -> int:
        return max(5, min(v, 120))

    @field_validator("sender_email", "sender_name")
    @classmethod
    def empty_to_none(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        return v or None


class MailPulseTestRequest(BaseModel):
    """POST /admin/settings/mailpulse/test — envoi de test vers les destinataires dédiés."""

    event: MailPulseEvent
    channel: MailPulseTestChannel = "both"
    dry_run: bool = True


class MailPulseTestResult(BaseModel):
    """Résultat d'un envoi de test individuel."""

    channel: Literal["email", "whatsapp"]
    recipient: str
    ok: bool
    status: str
    error_code: str | None = None
    error_message: str | None = None


class MailPulseTestResponse(BaseModel):
    """Réponse du moteur de test — jamais de vrais parents impliqués."""

    dry_run: bool
    event: MailPulseEvent
    sent: int
    results: list[MailPulseTestResult] = []
    message: str


class MailPulseInboundPayload(BaseModel):
    """Message WhatsApp entrant relayé par MailPulse (feature INFO).

    Contrat volontairement permissif : le numéro peut arriver sous ``from`` ou
    ``phone`` et le texte sous ``text`` ou ``body`` selon le relais.
    """

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    sender: str | None = Field(default=None, alias="from")
    phone: str | None = None
    text: str | None = None
    body: str | None = None

    def resolved_phone(self) -> str:
        return (self.sender or self.phone or "").strip()

    def message_text(self) -> str:
        return (self.text or self.body or "").strip()


class MailPulseInboundResult(BaseModel):
    """Accusé de traitement d'un message entrant."""

    status: Literal["ignored", "unknown_number", "replied", "disabled"]
    matched: bool = False
