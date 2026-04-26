"""Client Redis async — sessions, cache, blacklist refresh tokens."""

from collections.abc import AsyncGenerator

import redis.asyncio as aioredis

from app.core.config import settings

_redis_client: aioredis.Redis | None = None


def get_redis_client() -> aioredis.Redis:
    """Retourne le client Redis singleton (créé à la première demande)."""
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(  # type: ignore[no-untyped-call]
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis_client


async def get_redis() -> AsyncGenerator[aioredis.Redis, None]:
    """Dependency FastAPI — retourne le client Redis."""
    yield get_redis_client()
