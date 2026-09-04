"""La reprise de televersement : un telephone depose, un operateur confirme.

Le geste
========

Un ordinateur sans camera doit pouvoir recevoir une photo d'eleve. L'operateur
ouvre une session depuis son ecran, montre un code 2D, le telephone le scanne,
prend la photo et l'envoie. L'ordinateur voit arriver l'image, la regarde, et
c'est LUI qui confirme — avec sa propre session et sa propre permission.

Le telephone ne touche jamais une fiche. Il depose dans un sas
(`app/utils/handoff_storage.py`) et rien d'autre. C'est la propriete de securite
centrale du dispositif, et elle est ce qui rend acceptable qu'un jeton porteur
circule dans un code que n'importe qui peut photographier dans un couloir : le
pire qu'un code vole produit, c'est une image que l'operateur voit et refuse.

Pourquoi Redis et pas la base
=============================

Une session vit dix minutes. La stocker en base imposerait une migration sur
TOUTES les bases d'etablissement (une par ecole, `app/cli/migrate_all.py`), un
balayage de lignes mortes, et n'offrirait aucune expiration native. Redis fait
les trois gratuitement. Le precedent est dans le depot : la liste blanche des
jetons de rafraichissement y vit deja (`auth_service`), et le quota d'envoi
public s'appuie deja sur un script Lua (`app/core/middleware.py`).

Rancon assumee : Redis tombe, la reprise par code 2D est indisponible. La camera
directe et l'import de fichier ne doivent en aucun cas en dependre.

Le piege, et il est mortel : UNE instance Redis pour TOUTES les ecoles
=====================================================================

Il y a une base MySQL par etablissement, mais une seule instance Redis
(`REDIS_URL`, `app/core/config.py`). Une cle de session sans segment de tenant
serait une passerelle entre ecoles : le jeton de l'une ouvrirait une session
dans l'autre. Les deux cles portent donc le tenant, et il est verifie des deux
cotes — l'ordinateur le tient de son JWT, le telephone du chemin de son URL.

Ce n'est ni un JWT, ni un jeton d'acces personnel, ni un sceau
==============================================================

Le JWT exige un utilisateur et n'est pas revocable individuellement ; le jeton
d'acces personnel est attache a un compte et vit quatre-vingt-dix jours ; le
sceau d'un document est permanent et fait pour etre scanne mille fois. Le jeton
de reprise ne porte qu'une cible et qu'un envoi, expire en dix minutes, se
revoque, et n'est jamais stocke en clair : seul son SHA-256 sert de cle, comme
pour un jeton d'acces personnel.

Deux secrets, pas un : l'operateur ne manipule que l'identifiant de session
(sondage, apercu, confirmation), le telephone ne connait que le jeton. L'un ne
se deduit pas de l'autre.
"""

import logging
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from ipaddress import ip_address
from typing import Any, Literal
from urllib.parse import urlparse

import redis.asyncio as aioredis
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.dependencies import TokenData
from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.services.qr_svg import qr_svg

logger = logging.getLogger(__name__)

#: Duree de vie d'une session. Assez pour sortir un telephone, deverrouiller,
#: scanner, cadrer et envoyer en 3G ; trop court pour qu'un code affiche sur un
#: ecran que plus personne ne regarde reste une porte ouverte.
SESSION_TTL_SECONDS = 600

#: Nombre de reprises possibles avant qu'il faille rouvrir une session.
#: « Reprendre » ne repousse jamais l'echeance : elle est absolue.
MAX_RETAKES = 3

State = Literal["open", "receiving", "proposed", "done"]

#: Ce que l'ordinateur devra faire du depot une fois confirme.
#:
#: `finalise` : le sujet existe deja, le serveur promeut le fichier et appelle
#: la fonction metier qui ecrit la colonne.
#: `stage-only` : le sujet n'existe pas encore — a l'inscription, la photo est
#: prise AVANT la creation de la fiche. L'ordinateur recupere les octets et les
#: rend au formulaire, qui suit son chemin habituel.
Mode = Literal["finalise", "stage-only"]

#: Ce qu'une cible exige comme sujet.
#:
#: `required` : un identifiant, toujours (photo d'enseignant, piece jointe).
#: `optional` : avec identifiant on finalise, sans on rend les octets.
#: `self`     : le sujet EST l'appelant (photo de profil), jamais un autre.
#: `none`     : la cible est l'etablissement lui-meme (logo, tampon).
SubjectRule = Literal["required", "optional", "self", "none"]

Finaliser = Callable[[AsyncSession, "HandoffSession", str], Awaitable[None]]

#: Le tenant entre dans une cle Redis partagee par toutes les ecoles.
#:
#: Il arrive du chemin d'une URL publique cote telephone. Un segment porteur de
#: `:` ou de `*` melangerait deux espaces de noms ou ouvrirait un motif de
#: recherche : on le refuse plutot que de l'echapper.
_TENANT_VALIDE = re.compile(r"^[a-z0-9][a-z0-9-]{0,61}$")


# ---------------------------------------------------------------------------
# La porte d'entree
# ---------------------------------------------------------------------------
#
# Ce module portait mille deux cent trente-six lignes et cinq sujets. Il en
# garde un seul : les quatre gestes de l'operateur. Le registre des cibles et
# la machine a etats d'une session vivent desormais dans `upload_handoff/`.
#
# Les noms sont re-exposes ici parce que c'est par ce module que les routeurs
# et les tests passent — `import ... as svc`, puis `svc.TARGETS`. Deplacer le
# code ne doit pas deplacer la porte.

from app.services.upload_handoff._registre import (  # noqa: E402
    TARGETS,
    HandoffTarget,
)

# `noqa: F401` sur les trois scripts Lua : ils ne sont pas appeles ici, ils
# sont RE-EXPOSES. Le faux Redis des tests compare le script recu a ces
# constantes pour savoir quelle transition simuler ; les retirer parce
# qu'ils semblent inutilises casserait la moitie de la suite.
from app.services.upload_handoff._session import (  # noqa: E402
    _DEPOT_SCRIPT,  # noqa: F401
    _REPRISE_SCRIPT,  # noqa: F401
    _TRANSITION_SCRIPT,  # noqa: F401
    HandoffSession,
    _tenant_valide,
    _transition,
    caller_may_open,
    claim_for_upload,
    close_session,
    discreet_label,
    ensure_owner,
    get_target,
    load_by_token,
    load_session,
    mark_proposed,
    open_session,
    promote,
    public_view,
    receive_deposit,
    release_claim,
    request_retake,
    staged_bytes,
)

__all__ = [
    "TARGETS",
    "HandoffSession",
    "HandoffTarget",
    "caller_may_open",
    "claim_for_upload",
    "close_session",
    "discreet_label",
    "ensure_owner",
    "get_target",
    "load_by_token",
    "load_session",
    "mark_proposed",
    "open_session",
    "public_view",
    "receive_deposit",
    "release_claim",
    "request_retake",
    "staged_bytes",
]

# ---------------------------------------------------------------------------
# Ce que l'ordinateur demande
# ---------------------------------------------------------------------------
#
# Au-dessus : la mecanique d'une session (jeton, etats, sas). Ici : les quatre
# gestes de l'operateur — ouvrir, regarder, confirmer, reprendre. Ils vivent
# dans ce module et non dans le routeur parce que chacun est une decision, pas
# un branchement : quel droit exiger, quel libelle montrer, dans quel ordre
# promouvoir puis ecrire.


#: Le chemin de la page telephone, cote frontend. Meme forme que la page de
#: verification d'un document (`/verifier/{tenant}/{token}`) : le tenant est
#: dans le chemin, parce qu'un telephone n'a pas de session et que c'est la
#: seule chose qui dise quelle base ouvrir.
PUBLIC_PATH = "televerser"


def handoff_url(tenant: str, token: str) -> str:
    """L'URL absolue encodee dans le code QR."""
    return f"{settings.PUBLIC_BASE_URL.rstrip('/')}/{PUBLIC_PATH}/{_tenant_valide(tenant)}/{token}"


def public_base_warnings() -> list[str]:
    """Ce qui empechera le telephone d'arriver au bout du lien, dit a l'avance.

    Le code QR encode une URL ABSOLUE, construite depuis `PUBLIC_BASE_URL`. Or
    l'ordinateur est sur le reseau de l'ecole et le telephone sur sa donnee
    mobile : les deux ne voient pas le meme reseau. Une base pointant sur
    `localhost` ou sur une plage privee donne un code QR parfaitement valide qui
    mene a une page blanche, et l'operateur n'a aucun moyen de comprendre
    pourquoi — le telephone dit « site inaccessible », pas « votre serveur a mal
    configure une variable ».

    On avertit, on ne refuse pas : sur un poste de developpement la base EST
    `localhost`, et refuser d'ouvrir la session y rendrait l'ecran intestable.
    L'avertissement remonte a l'ecran de l'operateur ET dans les journaux, ce
    qui en fait la seule chose visible quand la configuration est fausse en
    production.

    Rien ici ne PROUVE la joignabilite : un nom public peut n'etre pas resolu
    depuis un reseau mobile, un pare-feu peut filtrer, un certificat peut
    manquer. Ce controle elimine les configurations dont on SAIT qu'elles
    echouent ; il ne remplace pas le scan reel depuis un telephone en donnee
    mobile, qui reste la seule verification qui vaille.
    """
    alertes: list[str] = []
    base = settings.PUBLIC_BASE_URL.strip()
    adresse = urlparse(base)
    hote = (adresse.hostname or "").lower()

    if adresse.scheme not in {"http", "https"} or not hote:
        alerte = (
            "L'adresse publique du site (PUBLIC_BASE_URL) n'est pas une URL absolue : "
            "le code QR ne mènera nulle part. Corrigez la configuration du serveur."
        )
        logger.warning("Reprise par code QR — %s", alerte)
        return [alerte]

    if _hote_local(hote):
        alertes.append(
            f"L'adresse publique du site ({base}) ne désigne que ce réseau : un téléphone "
            "sur sa donnée mobile n'y accédera pas. Le code QR ne fonctionnera que depuis "
            "le réseau de l'établissement, s'il y accède."
        )

    if adresse.scheme == "http":
        alertes.append(
            "Le site est servi en HTTP : le téléphone ne pourra pas ouvrir sa caméra en "
            "direct et proposera l'appareil photo du système à la place."
        )

    for alerte in alertes:
        logger.warning("Reprise par code QR — %s", alerte)
    return alertes


def _hote_local(hote: str) -> bool:
    """L'hote ne designe-t-il que le reseau local ?

    Deux familles : les noms qui ne se resolvent que sur place (`localhost`, le
    `.local` du mDNS, un nom sans point donc sans domaine) et les adresses IP
    des plages non routables sur Internet (RFC 1918, boucle locale, lien local,
    plages reservees).
    """
    if hote in {"localhost", "127.0.0.1", "::1"} or hote.endswith((".local", ".localhost")):
        return True
    try:
        adresse = ip_address(hote)
    except ValueError:
        # Un nom d'hote. Sans point, il n'a pas de domaine : il ne se resout que
        # sur un reseau qui le connait deja.
        return "." not in hote
    return bool(
        adresse.is_private
        or adresse.is_loopback
        or adresse.is_link_local
        or adresse.is_reserved
        or adresse.is_unspecified
    )


async def _label_eleve(db: AsyncSession, subject_id: int) -> str:
    from app.repositories import admin_repository as repo

    eleve = await repo.get_student_by_id(db, subject_id)
    if eleve is None:
        raise NotFoundError("Student", subject_id)
    return discreet_label(eleve.first_name, eleve.last_name)


async def _label_enseignant(db: AsyncSession, subject_id: int) -> str:
    from app.repositories import admin_repository as repo

    enseignant = await repo.get_teacher_by_id(db, subject_id)
    if enseignant is None:
        raise NotFoundError("Teacher", subject_id)
    return discreet_label(enseignant.first_name, enseignant.last_name)


async def _label_personnel(db: AsyncSession, subject_id: int) -> str:
    from app.repositories import admin_repository as repo

    personne = await repo.get_staff_by_id(db, subject_id)
    if personne is None:
        raise NotFoundError("Staff", subject_id)
    return discreet_label(personne.first_name, personne.last_name)


#: Les cibles dont le sujet porte un nom. Ce sont exactement celles dont la
#: regle de sujet est `required` ou `optional` — donc celles ou l'identifiant
#: demande par l'operateur EST le sujet retenu. Les autres n'ont personne a
#: nommer : un logo n'a pas de prenom, et la photo de profil est celle de qui
#: regarde l'ecran.
_LABELS: Mapping[str, Callable[[AsyncSession, int], Awaitable[str]]] = {
    "student_photo": _label_eleve,
    "student_document": _label_eleve,
    "teacher_photo": _label_enseignant,
    "staff_photo": _label_personnel,
}


async def resolve_label(db: AsyncSession, target: HandoffTarget, subject_id: int | None) -> str:
    """Le libelle discret de la session, lu en base et jamais recu du client.

    Deux raisons de ne pas laisser l'ecran l'envoyer. La premiere : ce libelle
    s'affiche sur un telephone que n'importe qui peut avoir en main, et un champ
    libre y ferait passer ce que l'appelant veut — le matricule, la classe, la
    date de naissance. La seconde : le charger ICI verifie du meme geste que le
    destinataire existe. Le decouvrir a la confirmation reviendrait a refuser
    une photo deja prise, l'eleve reparti.

    Chaine vide quand il n'y a personne a nommer : l'ecran affiche alors la
    nature du geste (`metier`), qui ne revele rien.
    """
    if subject_id is None:
        return ""
    charger = _LABELS.get(target.kind)
    return await charger(db, subject_id) if charger else ""


def operator_view(session: HandoffSession) -> dict[str, Any]:
    """Ce que l'ecran de l'operateur relit toutes les deux secondes.

    Symetrique de `public_view`, et deliberement un peu plus riche : celui qui
    lit ceci est authentifie, proprietaire de la session et titulaire du droit.
    Il voit l'etat, le mode et le type recu — de quoi choisir entre
    « Confirmer » et « Reprendre ».

    Toujours pas d'etat civil, et ce n'est pas un oubli : le libelle est le MEME
    que celui du telephone. C'est ce qui permet a l'operateur de verifier d'un
    coup d'oeil que les deux ecrans parlent de la meme personne.
    """
    return {
        "id": session.id,
        "state": session.state,
        "mode": session.mode,
        "label": session.label,
        "metier": session.target.metier,
        "expires_at": session.deadline,
        "retakes_left": session.retakes_left,
        "staged_mime": session.staged_mime,
    }


@dataclass(frozen=True)
class OpenedSession:
    """Ce qu'une ouverture rend a l'ecran de l'operateur.

    Le jeton en clair n'y figure pas seul : il ne vit que dans `url`, et `url`
    n'est la que parce qu'un ecran doit pouvoir montrer le lien a taper quand un
    telephone ne scanne pas.
    """

    session: HandoffSession
    url: str
    qr_svg: str
    warnings: tuple[str, ...]


async def _autoriser(db: AsyncSession, current_user: TokenData, target: HandoffTarget) -> None:
    """Le droit de la CIBLE, redemande a la matrice a chaque geste.

    Pas une fois a l'ouverture : a chaque appel. Une session vit dix minutes, et
    un droit retire pendant ce temps doit fermer la porte tout de suite — la
    photo n'est pas encore ecrite, c'est precisement le moment ou refuser coute
    le moins cher.
    """
    if not await caller_may_open(db, current_user, target):
        raise PermissionDeniedError(target.permission or target.kind)


async def start_session(
    redis: aioredis.Redis,
    db: AsyncSession,
    *,
    current_user: TokenData,
    target_kind: str,
    subject_id: int | None = None,
    extras: Mapping[str, str] | None = None,
) -> OpenedSession:
    """Ouvre une session de depot et rend de quoi peindre l'ecran de l'operateur.

    L'ordre compte : le droit d'abord, le destinataire ensuite, la session en
    dernier. Ouvrir puis verifier laisserait derriere chaque refus une session
    valide dix minutes, avec son jeton, pour un geste qu'on vient d'interdire.

    L'etablissement n'est pas un parametre : il vient du jeton de l'appelant,
    lui-meme deja confronte au tenant de la requete par `get_current_user`. Le
    laisser choisir ferait de cette route la passerelle inter-ecoles que la cle
    Redis s'applique a interdire.
    """
    target = get_target(target_kind)
    await _autoriser(db, current_user, target)
    label = await resolve_label(db, target, subject_id)

    session, token = await open_session(
        redis,
        tenant=current_user.tenant_id,
        target_kind=target.kind,
        owner_user_id=current_user.user_id,
        label=label,
        subject_id=subject_id,
        extras=extras,
    )
    url = handoff_url(session.tenant, token)
    return OpenedSession(
        session=session,
        url=url,
        qr_svg=qr_svg(url),
        warnings=tuple(public_base_warnings()),
    )


async def load_for_operator(
    redis: aioredis.Redis,
    db: AsyncSession,
    *,
    current_user: TokenData,
    session_id: str,
) -> HandoffSession:
    """La session, si elle est celle de cet operateur et qu'il en a toujours le droit.

    Deux verifications, et elles ne disent pas la meme chose. La propriete
    repond a « est-ce MA session » : deux personnes du secretariat detiennent le
    meme droit et travaillent en parallele. La permission repond a « ai-je
    encore le droit de ce geste » : elle vit dans la matrice, elle peut changer
    pendant la session, et le registre seul sait laquelle exiger pour cette
    cible.
    """
    session = await load_session(redis, tenant=current_user.tenant_id, session_id=session_id)
    ensure_owner(session, current_user.user_id)
    await _autoriser(db, current_user, session.target)
    return session


async def confirm_session(redis: aioredis.Redis, db: AsyncSession, session: HandoffSession) -> str:
    """Le regard de l'operateur devient une ecriture. Une seule fois.

    L'etat passe a `done` AVANT la promotion, et de facon indivisible : deux
    clics rapides sur « Confirmer » doivent produire une photo, pas deux
    fichiers ni — pour une piece jointe — deux lignes en base. Le second clic
    trouve un etat qui n'est plus `proposed` et repart avec un refus.

    Si la promotion echoue, le fichier est encore dans le sas et la session
    retourne a l'operateur : une panne de disque ne doit pas lui faire perdre
    une photo qu'il a sous les yeux. Si c'est l'ecriture metier qui echoue, le
    fichier est deja sorti du sas : l'erreur remonte telle quelle et la session
    reste fermee, parce que la retenter n'aurait plus rien a promouvoir.

    Sans destinataire il n'y a rien a ecrire : a l'inscription, la fiche n'existe
    pas encore. L'ecran recupere alors les octets par l'apercu puis revoque la
    session — c'est le mode `stage-only`, et le refus ci-dessous est ce qui
    empeche de sortir un fichier du sas pour ne l'attacher a personne.
    """
    if session.mode == "stage-only":
        raise HTTPException(
            status_code=409,
            detail="Ce dépôt n'a pas de destinataire : récupérez l'image par l'aperçu.",
        )
    target = session.target
    if target.finalise is None:  # pragma: no cover - toute cible du registre en porte une
        raise HTTPException(status_code=409, detail="Ce type de dépôt ne sait pas se confirmer")

    if not await _transition(redis, session, depuis="proposed", vers="done"):
        raise HTTPException(status_code=409, detail="Aucun dépôt à confirmer")

    try:
        url = promote(session)
    except Exception:
        await _transition(redis, session, depuis="done", vers="proposed")
        raise

    await target.finalise(db, session, url)
    await close_session(redis, session)
    return url
