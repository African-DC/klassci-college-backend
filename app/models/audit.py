"""Re-export de AuditLog depuis app.core.audit pour Alembic autogenerate."""

from app.core.audit import AuditAction, AuditLog

__all__ = ["AuditAction", "AuditLog"]
