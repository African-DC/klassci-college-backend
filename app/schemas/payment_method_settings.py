"""Schémas de l'écran « Moyens de paiement par profil »."""

from pydantic import BaseModel, Field


class PaymentMethodDescriptor(BaseModel):
    """Un moyen de paiement tel que l'écran doit le présenter."""

    key: str
    label: str
    #: Vrai pour les espèces seulement. L'écran s'en sert pour avertir
    #: qu'autoriser ce moyen engage une journée de caisse à ouvrir et à
    #: compter le soir.
    requires_cash_drawer: bool


class PaymentMethodRoleConfig(BaseModel):
    """Ce qu'un profil qui encaisse a le droit de saisir."""

    role_id: int
    #: Nom technique du rôle, porté par les comptes et par l'audit.
    role_name: str
    #: Libellé montré à l'écran (« Comptable / Trésorier »).
    role_label: str
    allowed_methods: list[str]


class PaymentMethodSettingsResponse(BaseModel):
    methods: list[PaymentMethodDescriptor]
    roles: list[PaymentMethodRoleConfig]


class PaymentMethodRoleUpdate(BaseModel):
    role_id: int
    allowed_methods: list[str] = Field(default_factory=list)


class PaymentMethodSettingsUpdate(BaseModel):
    """Mise à jour partielle : seuls les profils envoyés sont modifiés."""

    roles: list[PaymentMethodRoleUpdate] = Field(default_factory=list)
