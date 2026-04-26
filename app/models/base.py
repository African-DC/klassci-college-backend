"""Mixin de base partagé par tous les modèles SQLAlchemy."""

import enum
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column


def ValueEnum(enum_cls: type[enum.Enum], name: str, **kw: Any) -> SAEnum:
    """Wrapper SQLAlchemy Enum qui mappe par .value (lowercase) et non .name (UPPERCASE)."""
    return SAEnum(enum_cls, name=name, values_callable=lambda e: [x.value for x in e], **kw)


class TimestampMixin:
    """Ajoute created_at et updated_at sur le serveur DB."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
