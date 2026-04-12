"""Audit log — enregistre toutes les mutations sensibles en base."""

import enum
import logging
from datetime import datetime
from typing import Any

import sqlalchemy.exc
from sqlalchemy import JSON, BigInteger, DateTime, Enum, String, Text, func, insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

logger = logging.getLogger(__name__)


def _sanitize(value: object) -> str:
    """Sanitize a value for safe logging (prevent log injection)."""
    return str(value).replace("\n", "\\n").replace("\r", "\\r")


class AuditAction(str, enum.Enum):
    """Actions auditables — utilisé à la fois comme type Python et comme ENUM MySQL."""

    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    LOGIN = "login"
    LOGOUT = "logout"


class AuditLog(Base):
    """Table des logs d'audit — une ligne par mutation sensible."""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    action: Mapped[str] = mapped_column(
        Enum(
            AuditAction,
            name="audit_action",
            values_callable=lambda e: [member.value for member in e],
        ),
        nullable=False,
    )
    old_values: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    new_values: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


async def audit_log(
    db: AsyncSession,
    *,
    entity_type: str,
    action: AuditAction,
    user_id: int | None = None,
    entity_id: int | None = None,
    old_values: dict[str, Any] | None = None,
    new_values: dict[str, Any] | None = None,
    ip_address: str | None = None,
    notes: str | None = None,
) -> None:
    """Enregistre une entrée d'audit dans la transaction courante.

    Utilise flush() — pas commit() — afin de ne pas rompre la transaction
    du service appelant. Le commit est de la responsabilité du service.

    À appeler sur toutes les mutations sensibles :
    paiements, notes, inscriptions, rôles/permissions.
    """
    try:
        stmt = insert(AuditLog).values(
            user_id=user_id,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            old_values=old_values,
            new_values=new_values,
            ip_address=ip_address,
            notes=notes,
        )
        await db.execute(stmt)
        await db.flush()
    except sqlalchemy.exc.DBAPIError:
        # Vraies erreurs DB (OperationalError, IntegrityError, etc.) — swallow.
        # DBAPIError hérite de StatementError, il faut le traiter en premier.
        logger.exception(
            "Failed to write audit log: entity_type=%s entity_id=%s action=%s",
            _sanitize(entity_type),
            _sanitize(entity_id),
            _sanitize(action),
        )
    except (
        sqlalchemy.exc.InvalidRequestError,  # session corrompue / mauvais état
        sqlalchemy.exc.StatementError,  # valeur Python non sérialisable, enum mal mappé
        TypeError,
        AttributeError,
    ):
        # Erreurs de programmation — propager au service afin d'éviter un
        # commit sur une session dans un état indéfini.
        raise
    except Exception:
        logger.exception(
            "Failed to write audit log: entity_type=%s entity_id=%s action=%s",
            _sanitize(entity_type),
            _sanitize(entity_id),
            _sanitize(action),
        )
        # Ne jamais faire échouer la requête principale à cause d'une erreur DB
        # sur la table d'audit (ex : contrainte, timeout réseau).
