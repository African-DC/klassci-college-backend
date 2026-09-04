"""Le dépôt depuis le téléphone — la porte publique de la reprise par code QR.

Elle s'ouvre sur un téléphone sans session, sur une donnée mobile, à partir
d'un code affiché sur un écran de bureau. Il n'y a donc ni jeton d'accès, ni
cookie, ni rien à quoi rattacher l'appelant : la seule chose qu'il présente est
le jeton du chemin, et ce jeton ouvre exactement une session de dépôt, une fois,
pendant dix minutes.

Ce que cette route N'ÉCRIT PAS
==============================

Aucune fiche. Aucune colonne. Le `POST` dépose dans un sas
(`app/utils/handoff_storage.py`) et fait passer la session à « proposée » ; il
n'ouvre même aucune base de données. L'écriture attend un opérateur devant son
propre écran, avec sa propre session et sa propre permission, qui aura d'abord
regardé l'image.

C'est ce qui rend acceptable qu'un jeton porteur circule dans un code que
n'importe qui peut photographier : le pire qu'un code volé produit, c'est une
image qu'un humain voit et refuse.

Ce qu'elle ne révèle pas
========================

Ni matricule, ni classe, ni date de naissance, ni nom complet. Le libellé vaut
« Kouadio A. » — assez pour cadrer la bonne personne, pas assez pour identifier
un mineur à partir d'un code ramassé dans un couloir. Le même libellé s'affiche
sur l'écran de l'opérateur, pour qu'il vérifie que les deux écrans parlent bien
de la même session.

Les trois listes qu'un préfixe public doit rejoindre
====================================================

1. `_GARDES_ENVOI_PUBLIC` (`app/core/middleware.py`) — sans quoi ni plafond de
   corps, ni quota par minute, ni limite d'envois simultanés.
2. La liste de préfixes de `_tenant_from_public_path` (`app/core/middleware.py`)
   — sans quoi le tenant du chemin n'est pas lu, et la MAUVAISE base s'ouvre,
   en silence.
3. `ROUTES_PUBLIQUES` (`scripts/check_permissions.py`) — sans quoi
   l'intégration continue sort « route sans garde ».

Chacune donne un échec d'une nature différente, et deux d'entre eux ne se
voient pas en recette mono-établissement. Les trois sont faites.
"""

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, File, Request, Response, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_tenant_db
from app.core.middleware import trusted_client_ip
from app.core.redis import get_redis
from app.schemas.upload_handoff import PublicHandoffReceived, PublicHandoffView
from app.services import upload_handoff_service as svc
from app.services._school_settings_helper import load_school_settings_for_pdf

router = APIRouter(prefix="/public/upload-handoff", tags=["public"])

#: Une page de dépôt ne s'indexe pas et ne se met pas en cache.
#:
#: Les mêmes en-têtes que la vérification publique de document, et pour une
#: raison de plus : l'URL porte un jeton. Un proxy d'établissement qui garderait
#: cette réponse la servirait au suivant.
_PUBLIC_HEADERS = {
    "X-Robots-Tag": "noindex, nofollow",
    "Cache-Control": "no-store, private",
}


@router.get("/{tenant}/{token}", response_model=PublicHandoffView)
async def describe_handoff(
    tenant: str,
    token: str,
    response: Response,
    redis: aioredis.Redis = Depends(get_redis),
    db: AsyncSession = Depends(get_tenant_db),
) -> PublicHandoffView:
    """Ce que le téléphone a le droit de savoir pour peindre sa page.

    404 quand le jeton a expiré ou a déjà servi, et c'est la réponse normale au
    bout de dix minutes : la page doit y lire « ce lien n'est plus valable »,
    pas une panne. Une session expirée et une session inconnue rendent la même
    chose — les distinguer dirait à qui essaie des jetons lesquels ont existé.
    """
    response.headers.update(_PUBLIC_HEADERS)
    session = await svc.load_by_token(redis, tenant=tenant, token=token)
    school = await load_school_settings_for_pdf(db)
    return PublicHandoffView(
        school_name=school.get("school_name") or "",
        **svc.public_view(session),
    )


@router.post("/{tenant}/{token}", response_model=PublicHandoffReceived)
async def deposit_handoff(
    tenant: str,
    token: str,
    request: Request,
    response: Response,
    file: UploadFile = File(...),
    redis: aioredis.Redis = Depends(get_redis),
) -> PublicHandoffReceived:
    """Le téléphone dépose son image dans le sas. Rien d'autre ne bouge.

    Pas de `get_tenant_db` : cette route n'ouvre aucune base. C'est la forme la
    plus courte de sa promesse — elle ne peut pas écrire une fiche, elle n'a
    pas de session pour le faire.

    L'adresse du téléphone est rangée dans la session, et nulle part ailleurs.
    Elle sera journalisée à la confirmation : l'opérateur qui confirme est
    identifié par sa propre session, mais la seule trace de qui a réellement
    pris la photo est celle-ci.

    409 si un autre téléphone a déjà pris la main sur ce code — il est affiché
    sur un écran, dans une salle, et deux personnes peuvent le scanner. Un seul
    dépôt passe : le second écraserait le premier sans que l'opérateur ait rien
    vu passer.
    """
    response.headers.update(_PUBLIC_HEADERS)
    await svc.receive_deposit(
        redis,
        tenant=tenant,
        token=token,
        file=file,
        phone_ip=trusted_client_ip(request),
    )
    return PublicHandoffReceived()
