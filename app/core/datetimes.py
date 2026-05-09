"""Datetime helpers.

The DB uses naive `DateTime` columns (no `timezone=True`) so we
strip tzinfo from UTC `datetime.now()` everywhere. This helper exists
so the strip is one-line and consistent.
"""

from datetime import UTC, datetime


def utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)
