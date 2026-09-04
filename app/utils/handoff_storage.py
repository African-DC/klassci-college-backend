"""Le sas : les fichiers reçus d'un téléphone, avant qu'un humain les valide.

Pourquoi une racine à part
==========================

`UPLOAD_ROOT` est montée en entier sous `/uploads` par un `StaticFiles` brut
(`app/main.py`) : ni authentification, ni cloisonnement de tenant, et un nom de
fichier n'est qu'un préfixe suivi de huit caractères hexadécimaux. Tout ce qui
entre là est public à qui devine ces huit caractères. C'est acceptable pour une
photo que l'administration a validée et qui s'affiche déjà sur une fiche ; ça ne
l'est pas pour la photo d'un mineur qu'un téléphone vient d'envoyer et que
personne n'a encore regardée.

Le sas prend donc sa propre racine, `HANDOFF_ROOT`, et cette racine n'est montée
nulle part. Aucun `app.mount`, aucun `UploadKind` : le seul chemin de lecture
est un endpoint authentifié qui diffuse les octets. Déposer le sas sous
`UPLOAD_ROOT` « pour simplifier » suffirait à transformer une reprise de photo
en fuite ouverte, et rien dans le code ne le signalerait.

Ce que le sas n'est pas
=======================

Ce n'est pas un stockage. Un fichier y vit le temps d'une session de dépôt — dix
minutes — puis il est promu vers sa sorte définitive, ou effacé. Il n'a pas à
survivre à un redéploiement. Il doit en revanche être le MÊME dossier pour le
backend qui écrit et pour le worker qui balaie les orphelins : deux dossiers de
même nom dans deux conteneurs, et le balayeur regarde un dossier vide pendant
que les images s'entassent ailleurs.

La promotion ne réécrit pas l'URL
=================================

`promote_staged` ne construit aucune URL et ne choisit aucun nom : il relit les
octets et les passe à `save_bytes`, la porte unique de `photo_upload`. Un jumeau
qui referait ici le triplet nommer / écrire / construire l'URL rouvrirait
exactement la divergence dossier-écrit / URL-rendue que cette porte a fermée.
"""

import logging
import os
import re
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile

from app.core.config import settings
from app.core.uploads import UploadKind
from app.utils.photo_upload import read_capped, save_bytes

logger = logging.getLogger(__name__)

#: Racine du sas. Distincte d'`UPLOAD_ROOT`, et jamais montee en statique.
HANDOFF_ROOT = Path(settings.HANDOFF_ROOT)

#: Le nom d'un fichier du sas, tel que `write_staged` le fabrique.
#:
#: Ce nom fait l'aller-retour par Redis, qui est partage par tous les
#: etablissements : il revient donc comme une donnee, pas comme une constante du
#: programme. Le relire par cette expression avant de toucher au disque est ce
#: qui empeche `../../etc/passwd` d'arriver jusqu'a un `unlink`.
_NOM_STAGE = re.compile(r"^[a-zA-Z0-9_-]{1,64}_[0-9a-f]{8}\.[a-z0-9]{2,4}$")


def _en_production() -> bool:
    """Meme convention que `ensure_upload_dirs` : la production seule."""
    return settings.APP_ENV.lower() in {"production", "prod"}


def ensure_handoff_dir() -> None:
    """Cree la racine du sas, et refuse de demarrer si c'est impossible en production.

    Meme regle que `ensure_upload_dirs` (`app/core/uploads.py`) et pour la meme
    raison : en production, une racine absente ou en lecture seule signifie un
    volume mal monte, et l'echec doit se voir au demarrage plutot qu'au premier
    depot, un jour de rentree, sur le telephone de quelqu'un.

    Hors production l'echec reste un avertissement : `/app/handoff` n'est creable
    ni sur un poste de developpement ni sur un runner d'integration continue.
    """
    try:
        os.makedirs(HANDOFF_ROOT, exist_ok=True)
    except OSError:
        if _en_production():
            raise
        logger.warning("Sas de depot non creable : %s", HANDOFF_ROOT, exc_info=True)


def staged_path(nom: str) -> Path:
    """Le chemin disque d'un fichier du sas, ou 400 si le nom n'est pas des notres.

    Deux gardes, pas une : le nom doit correspondre a ce que `write_staged`
    fabrique, ET le chemin obtenu doit retomber a plat dans la racine du sas.
    C'est la discipline de `UploadKind.delete_public`, qui garde le meme genre de
    porte a partir d'une URL venue de la base.
    """
    if not _NOM_STAGE.match(nom):
        raise HTTPException(status_code=400, detail="Dépôt introuvable")
    chemin = HANDOFF_ROOT / nom
    try:
        if chemin.resolve().parent != HANDOFF_ROOT.resolve():
            raise HTTPException(status_code=400, detail="Dépôt introuvable")
    except OSError:
        raise HTTPException(status_code=400, detail="Dépôt introuvable") from None
    return chemin


async def write_staged(
    file: UploadFile,
    *,
    session_id: str,
    extension: str,
    max_bytes: int,
) -> str:
    """Ecrit un envoi dans le sas et rend le nom sous lequel il y vit.

    L'extension vient du type deja valide par l'appelant, jamais du nom envoye
    par le telephone — meme raison qu'en tete de `photo_upload` : un nom de
    fichier est une chaine choisie par le client, et `os.path.join` suit ce
    qu'on lui donne.

    Le nom porte l'identifiant de session pour qu'un fichier du sas se rattache a
    sa session sans consulter Redis : le balayeur des orphelins travaille sur le
    disque, pas sur les cles.
    """
    contenu = await read_capped(file, max_bytes)
    ensure_handoff_dir()
    nom = f"{session_id}_{uuid.uuid4().hex[:8]}.{extension}"
    staged_path(nom).write_bytes(contenu)
    return nom


def read_staged(nom: str) -> bytes:
    """Relit les octets deposes. 404 si le fichier n'est plus la.

    Le fichier peut avoir disparu sans que personne ne l'ait supprime : le sas
    vit dans un volume qu'un redeploiement recree, et une session dure dix
    minutes. L'absence est donc un cas normal, pas une panne.
    """
    chemin = staged_path(nom)
    try:
        return chemin.read_bytes()
    except OSError:
        raise HTTPException(status_code=404, detail="Dépôt introuvable ou expiré") from None


def delete_staged(nom: str | None) -> None:
    """Efface un fichier du sas. Une absence n'est pas une erreur.

    Appele a la confirmation, a la reprise, a la revocation et au balayage : les
    quatre chemins par lesquels un depot cesse d'exister. Aucun ne doit echouer
    parce que le fichier etait deja parti.
    """
    if not nom:
        return
    try:
        staged_path(nom).unlink(missing_ok=True)
    except (OSError, HTTPException):
        logger.warning("Fichier du sas non supprime : %s", nom, exc_info=True)


def promote_staged(nom: str, *, kind: UploadKind, prefix: str) -> str:
    """Sort un fichier du sas vers sa sorte definitive et rend son URL publique.

    Relecture puis ecriture, plutot qu'un `os.replace` : le sas et la racine des
    televersements sont deux volumes distincts, ou un renommage echoue
    (`EXDEV`), et surtout le nom et l'URL du fichier final n'appartiennent qu'a
    `save_bytes`. Un fichier du sas plafonne a dix megaoctets ; la copie coute
    moins cher que la divergence qu'un chemin d'ecriture parallele finirait par
    introduire.

    Le fichier du sas est efface ensuite, et seulement si l'ecriture a reussi :
    en cas d'echec, le depot reste consultable et l'operateur peut retenter.
    """
    ext = nom.rsplit(".", 1)[-1]
    url = save_bytes(read_staged(nom), kind=kind, prefix=prefix, ext=ext)
    delete_staged(nom)
    return url
