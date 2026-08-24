"""Router « Moyens de paiement par profil » — paramètres de l'établissement.

Séparé du router `admin`, déjà bien assez long, et identifiable au premier
coup d'oeil. Les droits sont ceux de la gestion des rôles : c'est la même
matrice, présentée en clair.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import TokenData, get_current_user, get_tenant_db, require_permission
from app.schemas.payment_method_settings import (
    PaymentMethodSettingsResponse,
    PaymentMethodSettingsUpdate,
)
from app.services import payment_method_settings as service

router = APIRouter(prefix="/admin/payment-methods", tags=["admin", "payments"])


@router.get(
    "",
    response_model=PaymentMethodSettingsResponse,
    summary="Moyens de paiement autorisés par profil",
)
async def get_payment_method_settings(
    _: None = require_permission("admin:roles:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> PaymentMethodSettingsResponse:
    """Liste les moyens existants et, pour chaque profil qui encaisse, les siens."""
    return await service.get_settings(db)


@router.put(
    "",
    response_model=PaymentMethodSettingsResponse,
    summary="Régler les moyens de paiement d'un ou plusieurs profils",
)
async def update_payment_method_settings(
    data: PaymentMethodSettingsUpdate,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("admin:roles:write"),
    db: AsyncSession = Depends(get_tenant_db),
) -> PaymentMethodSettingsResponse:
    """Applique la configuration et renvoie l'état complet après écriture.

    Seuls les profils présents dans le corps sont modifiés, et seuls leurs
    droits `payments:method:*` : les autres permissions du rôle sont laissées
    intactes.
    """
    return await service.update_settings(db, data, updated_by=current_user.user_id)
