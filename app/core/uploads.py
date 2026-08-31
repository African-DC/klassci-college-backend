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


PHOTOS = UploadKind("photos", 5 * _MO)
SIGNATURES = UploadKind("signatures", 5 * _MO)
LOGOS = UploadKind("logos", 5 * _MO)
DOCUMENTS = UploadKind("documents", 10 * _MO)

KINDS: tuple[UploadKind, ...] = (PHOTOS, SIGNATURES, LOGOS, DOCUMENTS)


def ensure_upload_dirs() -> None:
    """Cree la racine et ses sous-dossiers, et refuse de demarrer si c'est impossible.

    En production, une racine absente ou en lecture seule signifie un volume mal
    monte. Avaler l'erreur donnerait un service qui demarre vert, sert 404 sur
    chaque image et ne casse qu'au premier televersement, des jours plus tard,
    a l'impression d'un bulletin. On prefere l'echec au demarrage, qui se voit.

    Hors production, l'echec reste un avertissement : la racine par defaut n'est
    pas creable sur un poste de developpement ni en integration continue, et
    refuser de demarrer y empecherait de lancer l'API entiere pour une fonction
    annexe.
    """
    for directory in (UPLOAD_ROOT, *(kind.directory for kind in KINDS)):
        try:
            os.makedirs(directory, exist_ok=True)
        except OSError:
            if settings.APP_ENV != "development":
                raise
            logger.warning("Dossier d'upload non creable : %s", directory, exc_info=True)


def delete_public_file(url: str | None) -> None:
    """Efface le fichier derriere une URL `/uploads/...`, si elle en designe un.

    Remplacer un logo laissait l'ancien fichier sur le disque pour toujours.
    Tant que le stockage etait jetable la fuite mourait avec le conteneur ;
    maintenant qu'il persiste, chaque remplacement deviendrait un dechet
    definitif dans le volume.

    L'URL vient de la base, donc d'une ecriture precedente, mais on ne lui fait
    pas confiance pour autant : seul un chemin qui retombe reellement sous un
    dossier connu est efface. Une URL etrangere, relative ou remontante est
    ignoree en silence, et l'absence du fichier n'est pas une erreur.
    """
    if not url:
        return
    for kind in KINDS:
        prefixe = f"{kind.url_prefix}/"
        if not url.startswith(prefixe):
            continue
        cible = kind.path_for(url[len(prefixe) :])
        try:
            racine = kind.directory.resolve()
            chemin = cible.resolve()
            if chemin.parent != racine:
                return
            chemin.unlink(missing_ok=True)
        except OSError:
            logger.warning("Ancien fichier non supprime : %s", cible, exc_info=True)
        return
