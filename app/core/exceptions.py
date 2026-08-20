"""Exceptions métier typées + handlers FastAPI."""

import logging
import re

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

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


# ---------------------------------------------------------------------------
# Contraintes de base de donnees
# ---------------------------------------------------------------------------

# MySQL : 1062 = doublon sur un index unique, 1451/1452 = cle etrangere.
_DUPLICATE_CODES = (1062,)
_FOREIGN_KEY_CODES = (1451, 1452)

# « Duplicate entry 'Inscription' for key 'fee_categories.name' »
_DUPLICATE_VALUE = re.compile(r"Duplicate entry '([^']*)'")


def _mysql_errno(exc: IntegrityError) -> int | None:
    """Numero d'erreur MySQL porte par l'exception du driver."""
    args = getattr(exc.orig, "args", None)
    if args and isinstance(args[0], int):
        return args[0]
    return None


def integrity_error_message(exc: IntegrityError) -> tuple[int, str, str]:
    """Traduit une contrainte violee en message lisible par un secretariat.

    Sans ca, MySQL remonte jusqu'a Starlette qui repond un `500 Internal
    Server Error` en texte brut : le front n'a plus qu'un « Erreur serveur »
    generique, alors que la cause est parfaitement explicable — un nom deja
    pris, ou un element encore utilise ailleurs.
    """
    errno = _mysql_errno(exc)

    if errno in _DUPLICATE_CODES:
        found = _DUPLICATE_VALUE.search(str(exc.orig))
        value = found.group(1) if found else None
        detail = (
            f"« {value} » existe déjà. Choisissez un autre nom."
            if value
            else "Cet enregistrement existe déjà."
        )
        return 409, detail, "DUPLICATE"

    if errno in _FOREIGN_KEY_CODES:
        return (
            409,
            "Impossible de supprimer cet élément : il est encore utilisé ailleurs. "
            "Retirez d'abord ce qui en dépend.",
            "IN_USE",
        )

    return 409, "L'opération viole une contrainte de la base de données.", "CONSTRAINT"
