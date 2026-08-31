"""Stockage des pièces jointes (documents élève : PDF, images), servi via /uploads."""

import os
import uuid

from fastapi import HTTPException, UploadFile

from app.core.uploads import DOCUMENTS
from app.utils.photo_upload import EXTENSION_PAR_TYPE, read_capped

#: Conserve : des tests nomment encore le dossier des documents.
DOCUMENT_UPLOAD_DIR = DOCUMENTS.directory
# Les types d'image viennent de `photo_upload`, seule table de reference :
# les deux modules en portaient chacun une copie, et c'est la divergence qui a
# laisse vivre l'extraction dangereuse d'un cote pendant que l'autre etait
# correcte. Un document accepte en plus le PDF.
_ALLOWED_TYPES = {**EXTENSION_PAR_TYPE, "application/pdf": "pdf"}


async def save_document_upload(file: UploadFile, *, prefix: str) -> tuple[str, str]:
    """Valide et sauvegarde un document. Retourne (url, mime_type)."""
    mime = file.content_type or ""
    if mime not in _ALLOWED_TYPES:
        raise HTTPException(
            status_code=400, detail="Format invalide. Accepte : PDF, JPEG, PNG, WebP"
        )

    contenu = await read_capped(file, DOCUMENTS.max_bytes)

    os.makedirs(DOCUMENTS.directory, exist_ok=True)
    ext = _ALLOWED_TYPES[mime]
    filename = f"{prefix}_{uuid.uuid4().hex[:8]}.{ext}"
    DOCUMENTS.path_for(filename).write_bytes(contenu)

    return DOCUMENTS.public_url(filename), mime
