"""Router « Dettes d'un exercice précédent » — la politique de l'établissement.

Séparé du router `admin`, déjà bien assez long, et identifiable au premier coup
d'oeil — même raison que `payment_method_settings.py`.

## Le droit demandé, et celui qu'on n'a pas créé

Pas de domaine `settings:*` : un domaine à un membre n'en est pas un, et il
n'existerait sur aucune école déjà ouverte sans une seconde migration pour le
semer — donc un écran vide en production le jour de la livraison.

L'écran est gardé par `admin:fee-categories:*`, porté par `admin` et `director`
seulement. C'est le droit « je fixe les règles d'argent de cette école », et
décider qu'une ardoise de l'an dernier bloque une réinscription en fait
manifestement partie. Le précédent existe déjà dans le dépôt :
`payment_method_settings.py` garde un écran de configuration par
`admin:roles:*`.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import TokenData, get_current_user, get_tenant_db, require_permission
from app.schemas.arrears_policy import ArrearsPolicyResponse, ArrearsPolicyUpdate
from app.services import arrears_policy as service

router = APIRouter(prefix="/admin/arrears-policy", tags=["admin", "enrollments"])


@router.get(
    "",
    response_model=ArrearsPolicyResponse,
    summary="Politique de l'établissement sur les dettes d'un exercice précédent",
)
async def get_arrears_policy(
    _: None = require_permission("admin:fee-categories:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> ArrearsPolicyResponse:
    """Renvoie la politique en place et son seuil. `off` tant que rien n'a été décidé."""
    return await service.get_settings(db)


@router.put(
    "",
    response_model=ArrearsPolicyResponse,
    summary="Régler la politique sur les dettes d'un exercice précédent",
)
async def update_arrears_policy(
    data: ArrearsPolicyUpdate,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("admin:fee-categories:update"),
    db: AsyncSession = Depends(get_tenant_db),
) -> ArrearsPolicyResponse:
    """Enregistre la politique entière et journalise le changement.

    Les deux champs sont requis : ce réglage a deux commandes et s'énonce d'un
    coup, plutôt que de laisser un corps incomplet écrire à moitié — voir
    l'en-tête de `app/schemas/arrears_policy.py`.
    """
    return await service.update_settings(db, data, updated_by=current_user.user_id)
