"""Stockage des pièces jointes (documents élève : PDF, images), servi via /uploads."""

import os
import uuid

from fastapi import HTTPException, UploadFile

from app.core.uploads import DOCUMENTS_DIR
from app.utils.photo_upload import EXTENSION_PAR_TYPE

# Racine partagee, servie sous `/uploads` : voir `app.core.uploads`.
DOCUMENT_UPLOAD_DIR = DOCUMENTS_DIR
# Les types d'image viennent de `photo_upload`, seule table de reference :
# les deux modules en portaient chacun une copie, et c'est la divergence qui a
# laisse vivre l'extraction dangereuse d'un cote pendant que l'autre etait
# correcte. Un document accepte en plus le PDF.
_ALLOWED_TYPES = {**EXTENSION_PAR_TYPE, "application/pdf": "pdf"}
_MAX_BYTES = 10 * 1024 * 1024


async def save_document_upload(file: UploadFile, *, prefix: str) -> tuple[str, str]:
    """Valide et sauvegarde un document. Retourne (url, mime_type)."""
    mime = file.content_type or ""
    if mime not in _ALLOWED_TYPES:
        raise HTTPException(
            status_code=400, detail="Format invalide. Accepte : PDF, JPEG, PNG, WebP"
        )

    os.makedirs(DOCUMENT_UPLOAD_DIR, exist_ok=True)
    ext = _ALLOWED_TYPES[mime]
    filename = f"{prefix}_{uuid.uuid4().hex[:8]}.{ext}"

    content = await file.read()
    if len(content) > _MAX_BYTES:
        raise HTTPException(status_code=400, detail="Fichier trop volumineux (max 10 Mo)")

    with open(os.path.join(DOCUMENT_UPLOAD_DIR, filename), "wb") as f:
        f.write(content)

    return f"/uploads/documents/{filename}", mime
