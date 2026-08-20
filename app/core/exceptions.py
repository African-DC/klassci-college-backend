"""Exceptions métier typées + handlers FastAPI."""

import logging
import secrets

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from app.core.db_errors import integrity_error_message

logger = logging.getLogger(__name__)


class AppException(Exception):
    """Exception de base pour toutes les erreurs métier KLASSCI."""

    def __init__(self, status_code: int, detail: str, code: str = "ERROR") -> None:
        self.status_code = status_code
        self.detail = detail
        self.code = code
        super().__init__(detail)


class NotFoundError(AppException):
    def __init__(self, entity: str, entity_id: int | str) -> None:
        super().__init__(
            status_code=404,
            detail=f"{entity} with id {entity_id} not found",
            code="NOT_FOUND",
        )


class UnauthorizedError(AppException):
    def __init__(self, detail: str = "Authentication required") -> None:
        super().__init__(status_code=401, detail=detail, code="UNAUTHORIZED")


class PermissionDeniedError(AppException):
    def __init__(self, action: str = "") -> None:
        detail = f"Permission denied: {action}" if action else "Permission denied"
        super().__init__(status_code=403, detail=detail, code="PERMISSION_DENIED")


class ConflictError(AppException):
    def __init__(self, detail: str) -> None:
        super().__init__(status_code=409, detail=detail, code="CONFLICT")


class BusinessValidationError(AppException):
    """Erreur de validation métier — distinct de pydantic.ValidationError."""

    def __init__(self, detail: str) -> None:
        super().__init__(status_code=422, detail=detail, code="VALIDATION_ERROR")


# ---------------------------------------------------------------------------
# Handlers FastAPI
# ---------------------------------------------------------------------------


def register_exception_handlers(app: FastAPI) -> None:
    """Enregistre les handlers d'exception sur l'app FastAPI."""

    @app.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
        """Dernier filet : transforme l'imprevu en reponse exploitable.

        Sans lui, l'exception remonte a `ServerErrorMiddleware`, qui se trouve
        AU-DESSUS du middleware CORS : la reponse est du texte brut sans
        en-tete `Access-Control-Allow-Origin`, le navigateur la bloque, et
        l'utilisateur ne voit qu'une erreur reseau. Le probleme devient alors
        indiagnosticable depuis l'ecran.

        Le code de reference relie ce que l'utilisateur a lu a la ligne de
        journal exacte : il n'a plus a raconter ce qu'il faisait.
        """
        reference = secrets.token_hex(3).upper()
        logger.exception("Erreur inattendue [%s] sur %s", reference, request.url.path)
        return JSONResponse(
            status_code=500,
            content={
                "detail": (
                    "Une erreur inattendue est survenue. Communiquez le code "
                    f"{reference} a votre administrateur."
                ),
                "code": "INTERNAL",
                "reference": reference,
            },
        )

    @app.exception_handler(IntegrityError)
    async def integrity_error_handler(request: Request, exc: IntegrityError) -> JSONResponse:
        status_code, detail, code = integrity_error_message(exc)
        # Le detail technique reste dans les logs : le message rendu ne doit
        # jamais exposer un nom de table ou d'index a l'utilisateur.
        logger.warning("Contrainte violee sur %s : %s", request.url.path, exc.orig)
        return JSONResponse(status_code=status_code, content={"detail": detail, "code": code})

    @app.exception_handler(AppException)
    async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail, "code": exc.code},
        )
