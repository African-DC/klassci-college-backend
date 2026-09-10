"""Stockage des pièces jointes (documents élève : PDF, images), servi via /uploads."""

from fastapi import HTTPException, UploadFile

from app.core.uploads import DOCUMENTS
from app.utils.photo_upload import EXTENSION_PAR_TYPE, read_capped, save_bytes

# Les types d'image viennent de `photo_upload`, seule table de reference :
# les deux modules en portaient chacun une copie, et c'est la divergence qui a
# laisse vivre l'extraction dangereuse d'un cote pendant que l'autre etait
# correcte. Un document accepte en plus le PDF.
#
# Publique parce que la table EST la reponse a « ce chemin accepte-t-il ce
# type ? », et que la question se pose ailleurs qu'ici : un envoi arrive
# parfois par une autre porte que `save_document_upload`, et doit repondre la
# meme chose. En recopier une deuxieme quelque part rejouerait exactement la
# divergence que le commentaire ci-dessus raconte.
ALLOWED_DOCUMENT_TYPES = {**EXTENSION_PAR_TYPE, "application/pdf": "pdf"}


async def save_document_upload(file: UploadFile, *, prefix: str) -> tuple[str, str]:
    """Valide et sauvegarde un document. Retourne (url, mime_type)."""
    mime = file.content_type or ""
    if mime not in ALLOWED_DOCUMENT_TYPES:
        raise HTTPException(
            status_code=400, detail="Format invalide. Accepte : PDF, JPEG, PNG, WebP"
        )

    contenu = await read_capped(file, DOCUMENTS.max_bytes)
    url = save_bytes(contenu, kind=DOCUMENTS, prefix=prefix, ext=ALLOWED_DOCUMENT_TYPES[mime])

    return url, mime
