"""Exceptions métier typées + handlers FastAPI."""

import logging
import secrets
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from starlette.types import ASGIApp, Message, Receive, Scope, Send

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


class PaymentMethodNotAllowedError(AppException):
    """Refus d'encaissement par un moyen que l'appelant n'a pas le droit de saisir.

    Un `PermissionDeniedError` nu répondrait « Permission denied:
    payments:method:cash » à quelqu'un qui a une famille devant son guichet.
    Le détail porte donc le moyen refusé, ce que la personne PEUT faire, et
    vers qui l'envoyer.
    """

    def __init__(self, detail: str) -> None:
        super().__init__(status_code=403, detail=detail, code="PAYMENT_METHOD_NOT_ALLOWED")


class ConflictError(AppException):
    def __init__(self, detail: str) -> None:
        super().__init__(status_code=409, detail=detail, code="CONFLICT")


class BusinessValidationError(AppException):
    """Erreur de validation métier — distinct de pydantic.ValidationError."""

    def __init__(self, detail: str) -> None:
        super().__init__(status_code=422, detail=detail, code="VALIDATION_ERROR")


class AllocationInvariantError(AppException):
    """La ventilation d'un versement ne couvre pas le versement : on n'écrit rien.

    Distincte d'une `BusinessValidationError`, et pas par goût du détail : ce
    n'est PAS une erreur de saisie. La personne au guichet a tapé un montant
    juste ; c'est la répartition calculée par le programme qui ne retombe pas
    dessus. Sous le code `VALIDATION_ERROR`, l'écran l'enverrait corriger une
    saisie correcte, et le défaut resterait invisible dans les journaux, noyé
    parmi les vrais refus de saisie.

    Le tout dans le même statut 422 : du point de vue du client HTTP, la
    demande est bien refusée sans avoir rien écrit.
    """

    def __init__(self, detail: str) -> None:
        super().__init__(status_code=422, detail=detail, code="ALLOCATION_INVARIANT")


class EnrollmentBlockedByArrearsError(AppException):
    """Refus d'inscrire tant qu'une dette d'un exercice revolu n'est pas reglee.

    **402 et non 403.** Le depot distingue deja « il faut payer » de « vous
    n'avez pas le droit » : c'est le meme statut que la retenue d'un document
    officiel. L'ecran doit pouvoir proposer un chemin de paiement, ou la
    derogation, plutot qu'un refus sec.

    **Dediee, et surtout pas `BusinessValidationError`.** Sous ce code, le
    refus pour dette se confondrait avec « la classe est pleine » ou « l'annee
    n'existe pas » : trois causes, trois gestes differents au guichet, et un
    seul message a l'ecran.

    **Pas une `HTTPException` non plus.** La promotion de masse enveloppe
    chaque creation et range tout ce qui n'est pas une erreur de validation
    metier dans « Erreur inattendue, voir les logs » : un refus poli y
    deviendrait quarante-trois erreurs opaques le jour de la promotion. Une
    classe a soi rend ce cas reconnaissable partout ou il compte.

    Le detail est structure — code, message, montant, `can_override` — et non
    une phrase : c'est l'ecran qui compose ce que la personne au guichet lit,
    et il lui faut les pieces separement. Le montant qu'il porte suit la
    permission de l'appelant, `None` quand elle manque et jamais `0` : voir
    `app/services/enrollment_arrears.py`.
    """

    def __init__(self, detail: dict[str, Any]) -> None:
        super().__init__(
            status_code=402,
            # `AppException.detail` reste une phrase : c'est elle qui part dans
            # les journaux et dans `str(exc)`. La charge structuree voyage a
            # cote, et le handler dedie l'envoie a sa place au client.
            detail=str(detail.get("message", "")),
            code="ENROLLMENT_BLOCKED_BY_ARREARS",
        )
        self.payload = detail


# ---------------------------------------------------------------------------
# Le filet qui rattrape l'imprevu
# ---------------------------------------------------------------------------


def unexpected_error_response(path: str) -> JSONResponse:
    """Transforme l'imprevu en reponse exploitable, et journalise la trace.

    Le code de reference relie ce que l'utilisateur a lu a la ligne de journal
    exacte : il n'a plus a raconter ce qu'il faisait pour qu'on retrouve la
    panne.
    """
    reference = secrets.token_hex(3).upper()
    logger.exception("Erreur inattendue [%s] sur %s", reference, path)
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


class UnexpectedErrorMiddleware:
    """Rattrape l'imprevu SOUS le middleware CORS, pour que l'ecran le lise.

    Un `@app.exception_handler(Exception)` ne suffit pas : Starlette confie
    cette cle a `ServerErrorMiddleware`, qui coiffe toute la pile, CORS
    compris. La reponse produite la-haut ne repasse jamais par CORS, sort donc
    sans en-tete `Access-Control-Allow-Origin`, et le navigateur la bloque.
    L'utilisateur voit une erreur reseau, et le code de reference — la seule
    raison d'etre du dispositif — ne lui parvient jamais.

    Place sous CORS, la reponse remonte la pile normalement et ressort avec
    ses en-tetes.

    Starlette documente un autre remede : envelopper l'application entiere,
    `app = CORSMiddleware(app=app, ...)`, ce qui coiffe meme
    `ServerErrorMiddleware`. Ecarte ici parce que `app` cesserait alors d'etre
    une instance FastAPI, que plusieurs modules importent comme telle.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started = False

        async def _send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, _send)
        except Exception:
            if started:
                # Les en-tetes sont deja partis : plus moyen de rendre autre
                # chose. On laisse remonter, la trace sera journalisee au-dessus.
                raise
            response = unexpected_error_response(scope.get("path", ""))
            await response(scope, receive, send)


# ---------------------------------------------------------------------------
# Handlers FastAPI
# ---------------------------------------------------------------------------


def register_exception_handlers(app: FastAPI) -> None:
    """Enregistre les handlers d'exception sur l'app FastAPI."""

    @app.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
        """Ultime recours, pour ce qui echappe meme au middleware.

        Ce handler s'execute dans `ServerErrorMiddleware`, tout en haut de la
        pile : il ne couvre donc que les pannes du middleware CORS lui-meme.
        Tout le reste est attrape plus bas par `UnexpectedErrorMiddleware`,
        qui rend, lui, une reponse que le navigateur accepte.
        """
        return unexpected_error_response(request.url.path)

    @app.exception_handler(IntegrityError)
    async def integrity_error_handler(request: Request, exc: IntegrityError) -> JSONResponse:
        status_code, detail, code = integrity_error_message(exc)
        # Le detail technique reste dans les logs : le message rendu ne doit
        # jamais exposer un nom de table ou d'index a l'utilisateur.
        logger.warning("Contrainte violee sur %s : %s", request.url.path, exc.orig)
        return JSONResponse(status_code=status_code, content={"detail": detail, "code": code})

    @app.exception_handler(EnrollmentBlockedByArrearsError)
    async def enrollment_arrears_handler(
        request: Request, exc: EnrollmentBlockedByArrearsError
    ) -> JSONResponse:
        """Rend la charge structuree la ou le client attend le detail.

        Starlette choisit le handler en remontant la MRO de l'exception : celui
        d'`AppException` reste le filet de toutes les autres, et celui-ci passe
        devant pour la seule qui porte un detail compose.
        """
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.payload, "code": exc.code},
        )

    @app.exception_handler(AppException)
    async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail, "code": exc.code},
        )
