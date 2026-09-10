"""Poser une photo : écrire la colonne, journaliser le geste, effacer l'ancienne.

Les quatre chemins de photo — élève, enseignant, personnel, profil — faisaient
la même chose de la même façon incomplète : écraser une colonne, et rien
d'autre. Ce module tient les trois gestes ensemble parce qu'ils ne se séparent
pas : une photo remplacée sans trace n'est pas révocable, et une photo remplacée
sans effacement laisse un fichier que plus personne ne sait retrouver.

Ce qui manquait, et ce que ça coûtait
=====================================

**Aucun journal.** Les trois `update_*_photo` recevaient `updated_by` et ne
s'en servaient pas : pas une ligne d'audit. La photo d'un élève est la donnée
la plus personnelle que porte une fiche, et c'est la seule mutation sensible du
produit qui ne laissait pas de trace. La question « qui a mis cette photo, et
d'où » n'avait aucune réponse.

Avec le dépôt par téléphone, elle en a une qui compte davantage : l'opérateur
qui confirme est identifié par sa session, mais la photo a été prise ailleurs,
par un appareil qui n'a pas de compte. `ip_address` porte l'adresse du
téléphone, `notes` dit par quel chemin l'image est arrivée. C'est la seule
trace de qui a réellement appuyé sur le déclencheur.

**Aucun effacement.** `delete_public` n'était câblé que sur le logo et le
tampon de signature. Les photos, elles, s'écrasaient : le fichier précédent
restait sur le volume pour toujours. Tant que le stockage était jetable la
fuite mourait avec le conteneur ; depuis qu'il persiste, chaque remplacement
est un déchet définitif. La reprise par code 2D rend le remplacement courant —
chaque « Reprendre » est une photo de plus — donc la fuite grandirait
exactement à la vitesse du succès de la fonctionnalité.

L'ordre, et pourquoi il n'est pas indifférent
=============================================

Le fichier n'est effacé qu'APRÈS le `commit`. Si l'écriture échoue, la colonne
désigne encore l'ancienne photo : l'avoir effacée d'avance donnerait une fiche
dont l'image ne se charge plus, sans que rien ne l'ait signalé. L'inverse — un
fichier orphelin après un commit réussi — se rattrape ; une fiche qui pointe
vers un fichier supprimé, non.
"""

import logging
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditAction, audit_log
from app.core.uploads import PHOTOS

logger = logging.getLogger(__name__)


class PhotoHolder(Protocol):
    """Une fiche qui porte une photo : élève, enseignant, membre du personnel.

    Un protocole plutôt qu'une union de modèles : ce module n'a besoin de rien
    d'autre que de la colonne, et lui faire connaître les quatre modèles le
    rendrait solidaire de leurs imports pour rien.
    """

    photo_url: str | None


async def replace_photo(
    db: AsyncSession,
    holder: PhotoHolder,
    *,
    entity_type: str,
    entity_id: int,
    photo_url: str | None,
    updated_by: int,
    ip_address: str | None = None,
    notes: str | None = None,
) -> None:
    """Remplace la photo d'une fiche, journalise le geste, efface la précédente.

    `photo_url=None` retire la photo : c'est le même geste, et il mérite la
    même trace — retirer la photo d'un élève est une mutation comme une autre.

    `ip_address` et `notes` sont les deux champs que le dépôt par téléphone
    remplit : l'adresse d'où l'image est arrivée, et la session qui l'a portée.
    Sur les chemins ordinaires (l'opérateur téléverse depuis son écran), ils
    restent vides — l'adresse est déjà celle de la requête auditée, et il n'y a
    rien à préciser.

    Poser deux fois la même URL ne fait rien : ni ligne de journal, ni
    suppression. Le second appel effacerait le fichier que la colonne désigne
    encore.
    """
    ancienne = holder.photo_url
    if ancienne == photo_url:
        return

    holder.photo_url = photo_url
    await audit_log(
        db,
        entity_type=entity_type,
        entity_id=entity_id,
        action=AuditAction.UPDATE,
        user_id=updated_by,
        ip_address=ip_address,
        notes=notes,
        old_values={"photo_url": ancienne},
        new_values={"photo_url": photo_url},
    )
    await db.flush()
    await db.commit()

    # Après le commit, et pas avant : voir l'en-tête du module.
    #
    # `delete_public` ne suit une URL que si elle désigne bien un fichier de
    # SA sorte, à plat dans son dossier. Une URL étrangère, relative ou
    # remontante est ignorée en silence : cette garde était déjà écrite pour le
    # logo, elle n'avait simplement jamais servi sur le chemin des photos.
    PHOTOS.delete_public(ancienne)
