"""Helper pour wrapper la génération PDF de manière sûre côté router.

Sans ce wrapper, une exception non gérée (typiquement `OSError` quand
WeasyPrint ne trouve pas la GTK runtime, ou `TypeError` lors de la
sérialisation Pydantic→Jinja) remonte en 500 plain-text qui **bypass
le CORSMiddleware Starlette** — le browser bloque alors la réponse
sans header `Access-Control-Allow-Origin` et le FE affiche un toast
générique muet. Voir incident `project_session_2026_05_20_visual_check_e2e.md`.

En levant explicitement `HTTPException`, FastAPI/Starlette wrappe la
réponse dans le pipeline normal → CORS s'applique → le FE reçoit un
JSON `{detail: ...}` exploitable pour un toast utilisateur.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from fastapi import HTTPException, status
from fastapi.responses import Response

from app.core.exceptions import AppException

logger = logging.getLogger(__name__)


async def pdf_response(
    factory: Callable[[], Awaitable[bytes]],
    *,
    filename: str,
    error_context: str,
    disposition: str = "inline",
) -> Response:
    """Génère un PDF et le retourne comme `application/pdf`.

    `factory` est une coroutine sans args qui produit les bytes PDF.
    `error_context` est inclus dans le `detail` 500 pour faciliter le debug
    sans exposer la stack trace au client (ex: "bulletin 42").
    `disposition` : `inline` pour preview navigateur (défaut), `attachment`
    pour forcer le téléchargement direct (ex: export EDT, bordereau).
    """
    try:
        pdf_bytes = await factory()
    except AppException:
        raise
    except OSError as exc:
        logger.exception("PDF generation failed (%s): library load error", error_context)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                f"Génération PDF impossible pour {error_context}. "
                "Le serveur n'a pas pu charger la bibliothèque PDF (GTK/Cairo). "
                "Contactez l'administrateur système."
            ),
        ) from exc
    except Exception as exc:
        logger.exception("PDF generation failed (%s)", error_context)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Génération PDF impossible pour {error_context}.",
        ) from exc

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'{disposition}; filename="{filename}"'},
    )
