"""Exceptions métier typées + handlers FastAPI."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


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

    @app.exception_handler(AppException)
    async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail, "code": exc.code},
        )
