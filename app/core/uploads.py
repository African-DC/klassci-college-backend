"""Racine unique des fichiers televerses, servie par l'application sous `/uploads`.

Photos d'eleves, photos du personnel, tampon de signature et logo vivaient sous
`/tmp/klassci-uploads`. Le conteneur backend n'ayant aucun volume, chaque
redeploiement repartait d'un `/tmp` vide : les fichiers disparaissaient sans que
personne ne les ait supprimes. La racine est donc lue dans l'environnement
(`UPLOAD_ROOT`, defaut `/app/uploads`) et pointe sur un volume persistant.

Un seul module la definit : `app.main` monte `/uploads` dessus et les modules
d'ecriture y rangent leurs sous-dossiers. Les URL publiques ne changent pas,
`/uploads/photos/...` reste `/uploads/photos/...`.
"""

import logging
import os
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger(__name__)

#: Racine servie sous `/uploads`. A monter sur un volume persistant en production.
UPLOAD_ROOT = Path(settings.UPLOAD_ROOT)

PHOTOS_DIR = UPLOAD_ROOT / "photos"
SIGNATURES_DIR = UPLOAD_ROOT / "signatures"
LOGOS_DIR = UPLOAD_ROOT / "logos"
DOCUMENTS_DIR = UPLOAD_ROOT / "documents"

#: Cree au demarrage : un dossier absent fait echouer la premiere ecriture,
#: alors que le montage, lui, est bien la.
STARTUP_DIRS: tuple[Path, ...] = (
    UPLOAD_ROOT,
    PHOTOS_DIR,
    SIGNATURES_DIR,
    LOGOS_DIR,
    DOCUMENTS_DIR,
)


def ensure_upload_dirs() -> None:
    """Cree la racine et ses sous-dossiers si besoin.

    Un echec n'interrompt pas le demarrage : sur un poste de developpement ou
    en integration continue, la racine par defaut peut ne pas etre creable, et
    refuser de demarrer pour cela empecherait de lancer l'API entiere pour une
    fonction annexe. Le probleme ressort alors a la premiere ecriture, avec le
    chemin fautif deja trace ici.
    """
    for directory in STARTUP_DIRS:
        try:
            os.makedirs(directory, exist_ok=True)
        except OSError:
            logger.warning("Dossier d'upload non creable : %s", directory, exc_info=True)
