"""Sentry SDK initialization.

No-op si SENTRY_DSN n'est pas défini. Doit être appelé AVANT la création
de l'instance FastAPI() pour que les middlewares Sentry s'attachent
correctement.
"""

import logging
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)


def init_sentry() -> None:
    """Initialize Sentry if SENTRY_DSN is configured.

    Strips Authorization headers and cookies from events before sending.
    Safe to call when DSN is empty (early return, no SDK import).
    """
    if not settings.SENTRY_DSN:
        logger.info("Sentry disabled (no SENTRY_DSN configured)")
        return

    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
    from sentry_sdk.integrations.starlette import StarletteIntegration

    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.SENTRY_ENVIRONMENT or settings.APP_ENV,
        release=settings.APP_VERSION,
        traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
        profiles_sample_rate=0.0,
        send_default_pii=False,
        integrations=[
            StarletteIntegration(transaction_style="endpoint"),
            FastApiIntegration(transaction_style="endpoint"),
            SqlalchemyIntegration(),
        ],
        before_send=_strip_sensitive_data,  # type: ignore[arg-type]
    )
    logger.info(
        "Sentry initialized (env=%s release=%s traces=%.2f)",
        settings.SENTRY_ENVIRONMENT or settings.APP_ENV,
        settings.APP_VERSION,
        settings.SENTRY_TRACES_SAMPLE_RATE,
    )


_REDACT_HEADERS: frozenset[str] = frozenset({"authorization", "cookie", "x-api-key"})


def _strip_sensitive_data(event: dict[str, Any], _hint: dict[str, Any]) -> dict[str, Any]:
    """Remove auth headers + cookies from outbound Sentry events."""
    request = event.get("request")
    if isinstance(request, dict):
        headers = request.get("headers")
        if isinstance(headers, dict):
            for key in list(headers):
                if key.lower() in _REDACT_HEADERS:
                    headers[key] = "[redacted]"
        request.pop("cookies", None)
    return event
