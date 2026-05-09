"""Platform-level health checks for the super-admin diagnose endpoint.

Each check is an independent coroutine so we can fan them out with
``asyncio.gather`` and never let a slow component (Redis hung at ~1s) drag
down the entire dashboard.

Per-tenant deeper diagnostics (alembic head check, role/perm anomaly
detection) live in ``services.tenants.query`` already — only platform-wide
liveness lives here.
"""

import asyncio
import logging
from typing import Literal

from sqlalchemy import text

from app.core.config import settings
from app.core.database import management_database_url
from app.core.datetimes import utcnow_naive
from app.core.redis import get_redis_client
from app.services.tenants._engine import short_lived_engine

logger = logging.getLogger(__name__)

CheckStatus = Literal["ok", "degraded", "down"]
_DEGRADED_TIMEOUT_S = 2.0


async def check_database() -> tuple[CheckStatus, str | None]:
    try:
        async with short_lived_engine(
            management_database_url(), isolation_level="AUTOCOMMIT"
        ) as engine:
            async with engine.begin() as conn:
                await asyncio.wait_for(conn.execute(text("SELECT 1")), timeout=_DEGRADED_TIMEOUT_S)
        return "ok", None
    except TimeoutError:
        return "degraded", f"DB ping >{_DEGRADED_TIMEOUT_S}s"
    except Exception as exc:
        logger.exception("DB health check failed")
        return "down", _truncate(str(exc))


async def check_redis() -> tuple[CheckStatus, str | None]:
    try:
        client = get_redis_client()
        await asyncio.wait_for(client.ping(), timeout=_DEGRADED_TIMEOUT_S)
        return "ok", None
    except TimeoutError:
        return "degraded", f"Redis ping >{_DEGRADED_TIMEOUT_S}s"
    except Exception as exc:
        logger.exception("Redis health check failed")
        return "down", _truncate(str(exc))


def check_smtp_configured() -> tuple[CheckStatus, str | None]:
    """No live connection — just verify the config is non-empty.

    A real SMTP handshake takes 5-10s on AWS SES and would dominate the
    dashboard latency. The welcome-email path already logs failures.
    """
    if not settings.SMTP_HOST:
        return "degraded", "SMTP_HOST not set — welcome emails will be skipped"
    if not settings.SMTP_FROM_EMAIL:
        return "degraded", "SMTP_FROM_EMAIL not set"
    return "ok", None


def _truncate(msg: str, limit: int = 200) -> str:
    return msg if len(msg) <= limit else msg[:limit] + "…"


async def collect_platform_health() -> dict[str, object]:
    db_status, redis_status = await asyncio.gather(check_database(), check_redis())
    smtp_status = check_smtp_configured()

    checks = [
        {"component": "backend", "status": "ok", "message": None},
        {"component": "database", "status": db_status[0], "message": db_status[1]},
        {"component": "redis", "status": redis_status[0], "message": redis_status[1]},
        {"component": "smtp", "status": smtp_status[0], "message": smtp_status[1]},
    ]
    overall = _aggregate_status(check["status"] for check in checks)
    return {"overall": overall, "checks": checks, "timestamp": utcnow_naive()}


def _aggregate_status(statuses) -> CheckStatus:
    seen = set(statuses)
    if "down" in seen:
        return "down"
    if "degraded" in seen:
        return "degraded"
    return "ok"
