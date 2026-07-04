"""Schémas MailPulse — configuration tenant (get / update).

La clé API n'est JAMAIS renvoyée : la réponse expose seulement ``api_key_set``.
En update, une clé vide/absente conserve la clé existante.
"""

from pydantic import BaseModel, ConfigDict, field_validator


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
