"""Le côté ordinateur de la reprise par code QR — `/admin/upload-handoff`.

Pas de `from __future__ import annotations` : ce routeur porte un DELETE 204
`-> None` (cf. `rules/no-pep563-with-204.md`).

Où la permission s'applique, et pourquoi pas ici
================================================

Chaque route exige `get_current_user`, et rien d'autre en dépendance. Ce n'est
pas un oubli de `require_permission` : le droit à exiger n'est pas connu à la
déclaration de la route. Il dépend de ce qu'on photographie — un élève, un
enseignant, le logo de l'établissement — et vit dans le registre des cibles
(`upload_handoff_service.TARGETS`), donc il ne se résout qu'à l'exécution.

`require_permission` et `has_permission` sont toutes deux des **fabriques de
dépendances** : elles figent leur slug au moment où la route est écrite. Le seul
primitif qui prenne son slug à l'appel est `resolve_permission`, et c'est lui
que le service interroge, par `start_session` et `load_for_operator`. Le droit
est donc redemandé à la matrice à CHAQUE geste, pas seulement à l'ouverture :
une permission retirée pendant les dix minutes d'une session ferme la porte
avant que la photo ne soit écrite.

Ce que le routeur ne fait pas
=============================

Il n'ouvre pas de session, il ne promeut pas de fichier, il ne décide de rien :
tout cela est dans `upload_handoff_service`. Ici il n'y a que le transport —
lire la requête, appeler le service, rendre le schéma.
"""

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import TokenData, get_current_user, get_tenant_db
from app.core.redis import get_redis
from app.schemas.upload_handoff import (
    HandoffConfirmed,
    HandoffOpenRequest,
    HandoffRetaken,
    HandoffSessionOpened,
    HandoffSessionState,
)
from app.services import upload_handoff_service as svc

router = APIRouter(prefix="/admin/upload-handoff", tags=["upload-handoff"])

#: L'aperçu diffuse la photo d'un mineur que personne n'a encore validée.
#:
#: `no-store` plutôt que `no-cache` : rien ne doit s'écrire sur le disque du
#: poste, ni dans un proxy d'établissement. Mêmes en-têtes que les réponses
#: publiques de vérification de document, plus `nosniff` — le type vient d'un
#: dépôt téléphone, et il n'est pas question qu'un navigateur en devine un autre.
_APERCU_HEADERS = {
    "Cache-Control": "no-store, private",
    "X-Robots-Tag": "noindex, nofollow",
    "X-Content-Type-Options": "nosniff",
}


@router.post("", response_model=HandoffSessionOpened, status_code=status.HTTP_201_CREATED)
async def open_handoff(
    data: HandoffOpenRequest,
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_tenant_db),
    redis: aioredis.Redis = Depends(get_redis),
) -> HandoffSessionOpened:
    """Ouvre une session de dépôt et rend le code QR à montrer au téléphone."""
    ouverte = await svc.start_session(
        redis,
        db,
        current_user=current_user,
        target_kind=data.target_kind,
        subject_id=data.subject_id,
        extras=data.extras,
    )
    cible = ouverte.session.target
    return HandoffSessionOpened(
        **svc.operator_view(ouverte.session),
        url=ouverte.url,
        qr_svg=ouverte.qr_svg,
        accepts=sorted(cible.accepted_types),
        max_bytes=cible.max_bytes,
        warnings=list(ouverte.warnings),
    )


@router.get("/{session_id}", response_model=HandoffSessionState)
async def get_handoff(
    session_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_tenant_db),
    redis: aioredis.Redis = Depends(get_redis),
) -> HandoffSessionState:
    """Où en est cette session ? Sondée toutes les deux secondes tant qu'elle est ouverte.

    404 quand elle a expiré : c'est la réponse attendue au bout de dix minutes,
    et l'écran doit y lire « le code n'est plus valable », pas une panne.
    """
    session = await svc.load_for_operator(
        redis, db, current_user=current_user, session_id=session_id
    )
    return HandoffSessionState(**svc.operator_view(session))


@router.get("/{session_id}/preview", response_class=Response)
async def preview_handoff(
    session_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_tenant_db),
    redis: aioredis.Redis = Depends(get_redis),
) -> Response:
    """L'image proposée, diffusée octet par octet — le sas n'a pas d'URL.

    C'est le SEUL chemin de lecture du dépôt : sa racine n'est montée par aucun
    `StaticFiles`, donc il n'y a pas de nom de fichier à deviner. En mode
    `stage-only`, c'est aussi par ici que l'écran récupère l'image pour la
    rendre au formulaire d'inscription.
    """
    session = await svc.load_for_operator(
        redis, db, current_user=current_user, session_id=session_id
    )
    octets, mime = svc.staged_bytes(session)
    return Response(content=octets, media_type=mime, headers=_APERCU_HEADERS)


@router.post("/{session_id}/confirm", response_model=HandoffConfirmed)
async def confirm_handoff(
    session_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_tenant_db),
    redis: aioredis.Redis = Depends(get_redis),
) -> HandoffConfirmed:
    """L'opérateur a regardé l'image et l'accepte : elle est écrite sur la fiche.

    C'est le seul geste de toute la chaîne qui touche une colonne, et il part
    d'un écran authentifié. Un code QR volé ne produit donc jamais qu'une image
    que quelqu'un voit et refuse.
    """
    session = await svc.load_for_operator(
        redis, db, current_user=current_user, session_id=session_id
    )
    return HandoffConfirmed(url=await svc.confirm_session(redis, db, session))


@router.post("/{session_id}/retake", response_model=HandoffRetaken)
async def retake_handoff(
    session_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_tenant_db),
    redis: aioredis.Redis = Depends(get_redis),
) -> HandoffRetaken:
    """« Reprendre » : le dépôt est jeté, le même code QR redevient valable.

    L'échéance n'est pas repoussée — trois reprises ne doivent pas faire vivre
    une demi-heure un code affiché sur un écran de bureau.
    """
    session = await svc.load_for_operator(
        redis, db, current_user=current_user, session_id=session_id
    )
    return HandoffRetaken(retakes_left=await svc.request_retake(redis, session))


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_handoff(
    session_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_tenant_db),
    redis: aioredis.Redis = Depends(get_redis),
) -> None:
    """Ferme la session : le jeton n'ouvre plus rien et le dépôt est effacé.

    Appelée quand l'écran se ferme. Sans elle, un code QR resterait valable dix
    minutes sur un écran que plus personne ne regarde.
    """
    session = await svc.load_for_operator(
        redis, db, current_user=current_user, session_id=session_id
    )
    await svc.close_session(redis, session)
