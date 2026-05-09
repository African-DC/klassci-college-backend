"""Short-lived async engine context manager for cross-tenant ops.

Used by provisioning and query modules where we need a one-off
connection to either the management DB (for information_schema) or a
specific tenant DB. Always disposes cleanly even if the body raises.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


@asynccontextmanager
async def short_lived_engine(url: str, **kwargs: Any) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(url, **kwargs)
    try:
        yield engine
    finally:
        await engine.dispose()
