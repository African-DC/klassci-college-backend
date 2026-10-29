"""Persistent incident ledger; stored in the current school's database."""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin


class SupportIncident(Base, TimestampMixin):
    __tablename__ = "support_incidents"
    __table_args__ = (
        Index("ix_support_incidents_reference", "reference"),
        Index("ix_support_incidents_status_created", "status", "created_at"),
    )
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    reference: Mapped[str | None] = mapped_column(String(16), nullable=True)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(24), nullable=False, default="web")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="new")
    priority: Mapped[str] = mapped_column(String(16), nullable=False, default="normal")
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

class SupportIncidentEvent(Base):
    __tablename__ = "support_incident_events"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    incident_id: Mapped[str] = mapped_column(String(32), ForeignKey("support_incidents.id", ondelete="CASCADE"), nullable=False, index=True)
    actor_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    actor_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
