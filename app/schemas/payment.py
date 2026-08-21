"""Schémas Pydantic pour les paiements.

Architecture (refactor 2026-05-17) :
- `EnrollmentPaymentCreate` — body pour POST /enrollments/{id}/payments (cible).
- `PaymentCreate` — body legacy pour POST /payments (DEPRECATED, conservé pour rétrocompat).
- `PaymentResponse` — inclut maintenant `enrollment_id` + `allocations[]` + `status_label`.
- `PaymentAllocationPreview` — preview de l'allocation avant submit (UX caissier).
"""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_validator

from app.core.payment_methods import SELECTABLE_METHODS

#: Ce qu'un formulaire peut soumettre. `mobile_money` en est volontairement
#: absent : la valeur reste lisible en base mais n'est plus saisissable depuis
#: que les quatre operateurs ivoiriens sont distingues.
_ALLOWED_METHODS = set(SELECTABLE_METHODS)


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------


class EnrollmentPaymentCreate(BaseModel):
    """Body du nouvel endpoint POST /enrollments/{id}/payments (Wave-style)."""

    amount: Decimal
    method: str
    reference: str | None = None
    notes: str | None = None

    @field_validator("amount")
    @classmethod
    def amount_positive(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("amount must be positive")
        return v

    @field_validator("method")
    @classmethod
    def valid_method(cls, v: str) -> str:
        if v not in _ALLOWED_METHODS:
            raise ValueError(f"method must be one of {sorted(_ALLOWED_METHODS)}")
        return v


class PaymentCreate(BaseModel):
    """DEPRECATED — body legacy de POST /payments (cible un frais granulaire).

    Conservé pour rétrocompat ; le router log un warning. Tout nouveau code
    doit utiliser `EnrollmentPaymentCreate` + `POST /enrollments/{id}/payments`.
    """

    enrollment_fee_id: int
    amount: Decimal
    method: str
    reference: str | None = None
    notes: str | None = None

    @field_validator("amount")
    @classmethod
    def amount_positive(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("amount must be positive")
        return v

    @field_validator("method")
    @classmethod
    def valid_method(cls, v: str) -> str:
        if v not in _ALLOWED_METHODS:
            raise ValueError(f"method must be one of {sorted(_ALLOWED_METHODS)}")
        return v


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class PaymentAllocationResponse(BaseModel):
    """Un split d'un paiement vers un frais spécifique."""

    id: int
    enrollment_fee_id: int
    amount: Decimal
    fee_category_name: str | None = None
    fee_category_priority: int | None = None
    enrollment_fee_status_after: str | None = None

    model_config = ConfigDict(from_attributes=True)


class PaymentResponse(BaseModel):
    id: int
    #: `None` quand l'élève a été supprimé définitivement. Le versement, lui,
    #: reste : la caisse avait compté cet argent et les points journaliers
    #: déjà imprimés le disent. Le nom figé prend alors le relais.
    enrollment_id: int | None = None
    # DEPRECATED — conservé pour rétrocompat 1 release.
    enrollment_fee_id: int | None = None
    amount: Decimal
    method: str
    status: str
    reference: str | None
    received_by: int | None
    notes: str | None
    created_at: datetime
    updated_at: datetime
    # Enriched from joins
    student_name: str | None = None
    student_photo_url: str | None = None
    fee_name: str | None = None
    #: Identité figée, recopiée sur le versement avant la suppression de la
    #: fiche élève. Renseignée aussi dès la mise à la corbeille.
    student_matricule: str | None = None
    #: `True` quand la fiche élève n'existe plus. L'écran peut alors expliquer
    #: pourquoi la ligne ne mène nulle part, au lieu de proposer un lien mort.
    student_deleted: bool = False
    # Nouveaux champs (refactor 2026-05-17)
    allocations: list[PaymentAllocationResponse] = []


class PaymentListResponse(BaseModel):
    items: list[PaymentResponse]
    total: int
    page: int
    size: int


class PaymentSummaryResponse(BaseModel):
    """Les chiffres du tableau de bord, et ce qu'ils recouvrent exactement.

    `total_expected`, `total_paid` et `completion_rate` parlent de la même
    dette : les frais obligatoires encore dus, et l'argent imputé sur eux. Ils
    se comparent entre eux, et ils disent la même chose que la fiche de chaque
    élève.

    `total_pending`, `total_cancelled` et `payment_count` comptent des
    versements, pas des dettes — versements orphelins compris, pour ne pas
    dire moins que le bordereau de caisse du jour. Ils ne se comparent pas à
    `total_expected`.
    """

    total_expected: float
    total_paid: float
    total_pending: float
    total_cancelled: float
    payment_count: int
    completion_rate: float


# ---------------------------------------------------------------------------
# Allocation preview (UX caissier — appelle avant de submit)
# ---------------------------------------------------------------------------


class AllocationPreviewLine(BaseModel):
    """Une ligne du preview : combien irait à ce frais."""

    enrollment_fee_id: int
    fee_category_name: str
    fee_category_priority: int
    fee_total: Decimal
    fee_paid_before: Decimal
    allocated: Decimal
    fee_paid_after: Decimal
    status_after: str


class AllocationPreviewResponse(BaseModel):
    """Réponse du preview /enrollments/{id}/payments/preview?amount=X."""

    enrollment_id: int
    amount: Decimal
    total_remaining_before: Decimal
    total_remaining_after: Decimal
    surplus: Decimal
    can_record: bool
    reject_reason: str | None
    lines: list[AllocationPreviewLine]


# ---------------------------------------------------------------------------
# Moyens de paiement disponibles pour l'appelant
# ---------------------------------------------------------------------------


class PaymentMethodOption(BaseModel):
    """Une entrée du sélecteur d'encaissement."""

    key: str
    label: str


class PaymentMethodListResponse(BaseModel):
    """Ce que l'appelant peut saisir, déjà dans l'ordre d'affichage.

    L'ordre vient du serveur et suit la fréquence réelle au guichet ; l'écran
    n'a pas à le recalculer, et surtout pas à le retrier alphabétiquement.
    """

    items: list[PaymentMethodOption]
