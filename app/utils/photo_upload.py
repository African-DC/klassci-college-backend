"""Stockage des photos de profil (disque local, servi via /uploads)."""

import os
import uuid

from fastapi import HTTPException, UploadFile

from app.core.uploads import PHOTOS_DIR

# Racine partagee, servie sous `/uploads` : voir `app.core.uploads`.
PHOTO_UPLOAD_DIR = PHOTOS_DIR
_MAX_BYTES = 5 * 1024 * 1024

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


async def save_photo_upload(file: UploadFile, *, prefix: str) -> str:
    """Valide et sauvegarde une photo, retourne son URL publique `/uploads/photos/...`."""
    ext = extension_pour(file.content_type)

    os.makedirs(PHOTO_UPLOAD_DIR, exist_ok=True)
    filename = f"{prefix}_{uuid.uuid4().hex[:8]}.{ext}"

    content = await file.read()
    if len(content) > _MAX_BYTES:
        raise HTTPException(status_code=400, detail="Fichier trop volumineux (max 5 Mo)")

    with open(os.path.join(PHOTO_UPLOAD_DIR, filename), "wb") as f:
        f.write(content)

    return f"/uploads/photos/{filename}"
