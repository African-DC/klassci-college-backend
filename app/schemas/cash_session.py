"""Schémas de la caisse — session du jour, clôture, point journalier."""

from datetime import date as date_type
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CashMethodTotal(BaseModel):
    """Total encaissé par moyen de paiement, pour ventiler une journée."""

    method: str
    label: str
    count: int
    total: float


class CashSessionResponse(BaseModel):
    """Une journée de caisse : ouverte, clôturée, ou clôturée d'office.

    Les montants sont sérialisés en `float` et non en `Decimal` : Pydantic
    rend un Decimal sous forme de chaîne, ce que les contrats Zod du front
    rejettent (cf. `feedback_pydantic_decimal_zod_drift`).
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    cashier_user_id: int
    cashier_name: str
    business_date: date_type
    status: str
    opened_at: datetime
    closed_at: datetime | None = None
    # `None` sur une clôture d'office : le tiroir n'a pas été compté, et
    # l'écart est INCONNU. Surtout pas zéro, qui affirmerait qu'il tombait juste.
    counted_amount: float | None = None
    expected_amount: float | None = None
    variance: float | None = None
    notes: str | None = None
    # Renseigné quand une journée clôturée d'office a été comptée après coup.
    regularized_at: datetime | None = None

    # Vivant tant que la session est ouverte, figé à la clôture.
    payments_count: int = 0
    total_collected: float = 0.0
    cash_collected: float = 0.0
    by_method: list[CashMethodTotal] = Field(default_factory=list)


class CashSessionRegularizeRequest(BaseModel):
    """Comptage saisi après coup sur une journée clôturée d'office.

    Même charge utile que la clôture, mais requête distincte : la clôture
    refuse par principe une journée déjà verrouillée, et assouplir cette garde
    pour loger la régularisation ouvrirait aussi la porte aux journées
    régulièrement clôturées et signées.
    """

    counted_amount: float = Field(
        ...,
        ge=0,
        description="Espèces retrouvées dans le tiroir, en FCFA. Zéro est une valeur valide.",
    )
    notes: str | None = Field(
        None,
        max_length=1000,
        description="Pourquoi la journée n'a pas été clôturée, explication de l'écart.",
    )

    @field_validator("notes")
    @classmethod
    def _blank_to_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class CashSessionCloseRequest(BaseModel):
    """Clôture : le caissier déclare ce qu'il a compté dans son tiroir."""

    counted_amount: float = Field(
        ...,
        ge=0,
        description="Espèces réellement comptées, en FCFA. Zéro est une valeur valide.",
    )
    notes: str | None = Field(
        None,
        max_length=1000,
        description="Explication d'un écart, incident du jour, remise à la direction.",
    )

    @field_validator("notes")
    @classmethod
    def _blank_to_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class CashSessionListResponse(BaseModel):
    """Point journalier : toutes les caisses d'une date."""

    items: list[CashSessionResponse]
    business_date: date_type
    total_collected: float
    cash_collected: float
    total_variance: float
    open_count: int
    closed_count: int
    # Comptées à part : une journée clôturée d'office n'est ni une caisse
    # encore en service, ni une caisse arrêtée par quelqu'un.
    # Leur écart est inconnu : `total_variance` ne les couvre donc pas, et
    # ce compteur est ce qui empêche de le lire comme un solde complet.
    auto_closed_count: int = 0
