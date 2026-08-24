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


async def binary_response(
    factory: Callable[[], Awaitable[bytes]],
    *,
    filename: str,
    media_type: str,
    error_context: str,
    disposition: str = "inline",
) -> Response:
    """Genere un fichier binaire et l'expose sans jamais laisser fuir un 500 brut.

    Une exception non traitee dans une fabrique de document remonte en texte
    brut, contourne le pipeline d'erreurs, et le telechargement echoue en
    silence cote navigateur : l'utilisateur clique, rien ne se passe, et
    aucune trace exploitable n'arrive a l'ecran.

    `error_context` est repris dans le message d'erreur pour situer le
    document sans exposer la trace technique (ex. « bulletin 42 »).
    `disposition` : `inline` pour un apercu navigateur, `attachment` pour
    forcer le telechargement.
    """
    try:
        content = await factory()
    except AppException:
        raise
    except HTTPException:
        # Une regle metier levee dans la fabrique — la porte de paiement, par
        # exemple — doit remonter telle quelle. La transformer en 500
        # « generation impossible » masquerait la vraie raison du refus.
        raise
    except OSError as exc:
        logger.exception("Generation echouee (%s) : chargement de bibliotheque", error_context)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                f"Generation impossible pour {error_context}. "
                "Le serveur n'a pas pu charger une bibliotheque necessaire (GTK/Cairo). "
                "Contactez l'administrateur systeme."
            ),
        ) from exc
    except Exception as exc:
        logger.exception("Generation echouee (%s)", error_context)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Generation impossible pour {error_context}.",
        ) from exc

    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'{disposition}; filename="{filename}"'},
    )


async def pdf_response(
    factory: Callable[[], Awaitable[bytes]],
    *,
    filename: str,
    error_context: str,
    disposition: str = "inline",
) -> Response:
    """Genere un PDF et le retourne comme `application/pdf`.

    Cas particulier de `binary_response` : tout endpoint PDF passe par ici
    (rule `pdf-response-wrap.md`).
    """
    return await binary_response(
        factory,
        filename=filename,
        media_type="application/pdf",
        error_context=error_context,
        disposition=disposition,
    )
