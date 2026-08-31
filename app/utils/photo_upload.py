"""Ecriture des images televersees (disque local, servi via /uploads)."""

import os
import uuid

from fastapi import HTTPException, UploadFile

from app.core.uploads import PHOTOS, UploadKind

#: Conserve : plusieurs tests et modules nomment encore le dossier des photos.
PHOTO_UPLOAD_DIR = PHOTOS.directory

_TAILLE_LECTURE = 64 * 1024

# L'extension vient du type validé, jamais du nom envoyé par le client.
#
# `nom.rsplit(".", 1)[-1]` rend tout ce qui suit le dernier point, séparateurs
# compris : un fichier nommé `photo.png/../../../../app/main` donnait une
# extension `png/../../../../app/main`, et `os.path.join` la suivait hors du
# dossier d'upload. Un compte autorisé à changer une photo pouvait donc écrire
# n'importe où sur le serveur. Le type MIME est déjà contrôlé : s'en servir
# supprime la question plutôt que d'assainir une chaîne.
EXTENSION_PAR_TYPE = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}


def extension_pour(content_type: str | None) -> str:
    """L'extension d'un type d'image accepté. Lève 400 pour tout autre type."""
    extension = EXTENSION_PAR_TYPE.get(content_type or "")
    if extension is None:
        raise HTTPException(status_code=400, detail="Format invalide. Accepte : JPEG, PNG, WebP")
    return extension


async def read_capped(file: UploadFile, max_bytes: int) -> bytes:
    """Lit le fichier et s'arrête dès que la limite est franchie.

    Lire d'abord puis mesurer chargeait l'intégralité du corps en mémoire avant
    de le refuser : un envoi de 500 Mo était intégralement mis en RAM pour finir
    en 400. On lit donc par tranches et on abandonne au premier octet de trop.
    """
    morceaux: list[bytes] = []
    total = 0
    while morceau := await file.read(_TAILLE_LECTURE):
        total += len(morceau)
        if total > max_bytes:
            mo = max_bytes // (1024 * 1024)
            raise HTTPException(status_code=400, detail=f"Fichier trop volumineux (max {mo} Mo)")
        morceaux.append(morceau)
    return b"".join(morceaux)


async def save_image_upload(file: UploadFile, *, kind: UploadKind, prefix: str) -> str:
    """Valide et enregistre une image, retourne son URL publique.

    Seule porte d'entrée pour écrire une image : photo d'élève, d'enseignant, de
    membre du personnel, tampon de signature ou logo. Les cinq endpoints qui
    refaisaient ces sept gestes à la main portaient chacun sa propre limite de
    taille et construisait sa propre URL, et rien ne garantissait que le dossier
    écrit et l'URL rendue désignent le même endroit.
    """
    ext = extension_pour(file.content_type)
    contenu = await read_capped(file, kind.max_bytes)

    os.makedirs(kind.directory, exist_ok=True)
    filename = f"{prefix}_{uuid.uuid4().hex[:8]}.{ext}"
    kind.path_for(filename).write_bytes(contenu)

    return kind.public_url(filename)
