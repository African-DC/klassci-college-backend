"""Stockage des pièces jointes (documents élève : PDF, images), servi via /uploads."""

import os
import uuid

from fastapi import HTTPException, UploadFile

DOCUMENT_UPLOAD_DIR = "/tmp/klassci-uploads/documents"
_ALLOWED_TYPES = {
    "application/pdf": "pdf",
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}
_MAX_BYTES = 10 * 1024 * 1024


async def save_document_upload(file: UploadFile, *, prefix: str) -> tuple[str, str]:
    """Valide et sauvegarde un document. Retourne (url, mime_type)."""
    mime = file.content_type or ""
    if mime not in _ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail="Format invalide. Accepte : PDF, JPEG, PNG, WebP")

    os.makedirs(DOCUMENT_UPLOAD_DIR, exist_ok=True)
    ext = _ALLOWED_TYPES[mime]
    filename = f"{prefix}_{uuid.uuid4().hex[:8]}.{ext}"

    content = await file.read()
    if len(content) > _MAX_BYTES:
        raise HTTPException(status_code=400, detail="Fichier trop volumineux (max 10 Mo)")

    with open(os.path.join(DOCUMENT_UPLOAD_DIR, filename), "wb") as f:
        f.write(content)

    return f"/uploads/documents/{filename}", mime
