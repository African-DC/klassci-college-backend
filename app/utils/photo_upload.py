"""Stockage des photos de profil (disque local, servi via /uploads)."""

import os
import uuid

from fastapi import HTTPException, UploadFile

PHOTO_UPLOAD_DIR = "/tmp/klassci-uploads/photos"
_ALLOWED_TYPES = ("image/jpeg", "image/png", "image/webp")
_MAX_BYTES = 5 * 1024 * 1024


async def save_photo_upload(file: UploadFile, *, prefix: str) -> str:
    """Valide et sauvegarde une photo, retourne son URL publique `/uploads/photos/...`."""
    if file.content_type not in _ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail="Format invalide. Accepte : JPEG, PNG, WebP")

    os.makedirs(PHOTO_UPLOAD_DIR, exist_ok=True)
    ext = file.filename.rsplit(".", 1)[-1] if file.filename and "." in file.filename else "jpg"
    filename = f"{prefix}_{uuid.uuid4().hex[:8]}.{ext}"

    content = await file.read()
    if len(content) > _MAX_BYTES:
        raise HTTPException(status_code=400, detail="Fichier trop volumineux (max 5 Mo)")

    with open(os.path.join(PHOTO_UPLOAD_DIR, filename), "wb") as f:
        f.write(content)

    return f"/uploads/photos/{filename}"
