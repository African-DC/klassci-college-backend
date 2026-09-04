"""Racine unique des fichiers televerses, servie par l'application sous `/uploads`.

Photos d'eleves, photos du personnel, tampon de signature et logo vivaient sous
`/tmp/klassci-uploads`. Le conteneur backend n'ayant aucun volume monte, chaque
redeploiement repartait d'un `/tmp` vide : les fichiers disparaissaient sans que
personne ne les ait supprimes. La racine est donc lue dans l'environnement
(`UPLOAD_ROOT`, defaut `/app/uploads`) et pointe sur un volume persistant.

Un dossier et l'URL qui le sert ne sont pas deux informations : ce sont les deux
faces d'une meme. Les tenir separees, c'est laisser un endpoint ecrire dans
`signatures/` et rendre une URL `/uploads/photos/...`, et decouvrir la
divergence le jour ou un document sort sans son image. `UploadKind` les porte
donc ensemble, et c'est la seule maniere de nommer un emplacement ici.

Corollaire, et c'est le piege : TOUT ce qui vit sous cette racine est public.
Le montage est un `StaticFiles` brut, sans authentification ni cloisonnement de
tenant, et le nom d'un fichier n'est qu'un prefixe suivi de huit caracteres
hexadecimaux. Un fichier recu mais pas encore valide par un humain — la photo
qu'un telephone vient de deposer — n'a donc rien a faire ici : il attend dans le
sas de `app/utils/handoff_storage.py`, sous une racine qui n'est montee nulle
part. N'ajoutez pas d'`UploadKind` pour lui.
"""

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger(__name__)

_MO = 1024 * 1024

#: Racine servie sous `/uploads`. A monter sur un volume persistant en production.
UPLOAD_ROOT = Path(settings.UPLOAD_ROOT)


@dataclass(frozen=True)
class UploadKind:
    """Un emplacement de televersement : son dossier, son URL, sa taille limite.

    `directory` et `url_prefix` sont calcules a l'appel et non figes a l'import :
    un test qui deplace `UPLOAD_ROOT` deplace tout, sans avoir a repatcher chaque
    module qui ecrit.
    """

    name: str
    max_bytes: int

    @property
    def directory(self) -> Path:
        return UPLOAD_ROOT / self.name

    @property
    def url_prefix(self) -> str:
        return f"/uploads/{self.name}"

    def public_url(self, filename: str) -> str:
        """L'URL que le client recevra pour ce fichier."""
        return f"{self.url_prefix}/{filename}"

    def path_for(self, filename: str) -> Path:
        """Le chemin disque correspondant a `public_url(filename)`."""
        return self.directory / filename

    def delete_public(self, url: str | None) -> None:
        """Efface le fichier derriere une de MES URL, si elle en designe un.

        Remplacer un logo laissait l'ancien fichier sur le disque pour toujours.
        Tant que le stockage etait jetable la fuite mourait avec le conteneur ;
        maintenant qu'il persiste, chaque remplacement deviendrait un dechet
        definitif dans le volume.

        La sorte est celle de l'appelant, pas une devinette tiree de l'URL :
        l'endpoint du logo sait qu'il efface un logo. Une URL malformee ne peut
        donc pas atteindre le dossier d'une autre sorte, elle est simplement
        ignoree.

        L'URL vient de la base, donc d'une ecriture precedente, mais on ne lui
        fait pas confiance pour autant : seul un chemin qui retombe a plat dans
        mon dossier est efface. Une URL etrangere, relative ou remontante est
        ignoree en silence, et l'absence du fichier n'est pas une erreur.
        """
        prefixe = f"{self.url_prefix}/"
        if not url or not url.startswith(prefixe):
            return
        cible = self.path_for(url[len(prefixe) :])
        try:
            if cible.resolve().parent != self.directory.resolve():
                return
            cible.unlink(missing_ok=True)
        except OSError:
            logger.warning("Ancien fichier non supprime : %s", cible, exc_info=True)


PHOTOS = UploadKind("photos", 5 * _MO)
SIGNATURES = UploadKind("signatures", 5 * _MO)
LOGOS = UploadKind("logos", 5 * _MO)
DOCUMENTS = UploadKind("documents", 10 * _MO)

KINDS: tuple[UploadKind, ...] = (PHOTOS, SIGNATURES, LOGOS, DOCUMENTS)


def _en_production() -> bool:
    """La convention du projet, deja portee par `migrate_all` et les sceaux.

    Le test doit designer la production seule, et non « tout sauf un poste de
    developpement » : une integration continue tourne en `test`, et lui refuser
    le demarrage rendrait la suite de tests entierement rouge.
    """
    return settings.APP_ENV.lower() in {"production", "prod"}


def ensure_upload_dirs() -> None:
    """Cree la racine et ses sous-dossiers, et refuse de demarrer si c'est impossible.

    En production, une racine absente ou en lecture seule signifie un volume mal
    monte. Avaler l'erreur donnerait un service qui demarre vert, sert 404 sur
    chaque image et ne casse qu'au premier televersement, des jours plus tard,
    a l'impression d'un bulletin. On prefere l'echec au demarrage, qui se voit.

    Hors production, l'echec reste un avertissement : la racine par defaut n'est
    creable ni sur un poste de developpement ni sur un runner d'integration
    continue, et refuser de demarrer y empecherait de lancer l'API entiere, et
    de jouer la suite de tests, pour une fonction annexe.
    """
    for directory in (UPLOAD_ROOT, *(kind.directory for kind in KINDS)):
        try:
            os.makedirs(directory, exist_ok=True)
        except OSError:
            if _en_production():
                raise
            logger.warning("Dossier d'upload non creable : %s", directory, exc_info=True)
