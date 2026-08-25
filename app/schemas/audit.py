"""Schémas du journal d'audit."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class AuditEntryResponse(BaseModel):
    """Une ligne du journal : quand, qui, quoi, sur quoi."""

    id: int
    created_at: datetime
    action: str
    entity_type: str
    entity_id: int | None
    user_id: int | None
    # Nom résolu à la lecture depuis les fiches ; e-mail et rôle figés à
    # l'écriture, donc toujours là même si le compte a disparu.
    actor_name: str | None
    actor_email: str | None
    actor_role: str | None
    ip_address: str | None
    notes: str | None
    old_values: dict[str, Any] | None
    new_values: dict[str, Any] | None


class AuditListResponse(BaseModel):
    items: list[AuditEntryResponse]
    total: int
    page: int
    size: int


class AuditActorOption(BaseModel):
    user_id: int
    name: str | None
    email: str | None


class AuditFiltersResponse(BaseModel):
    """Ce que l'appelant a le droit de filtrer, et qui existe réellement.

    `scope` vaut `full` ou `financial` : l'écran doit pouvoir dire au comptable
    qu'il regarde une partie du journal, pas la totalité.
    """

    entity_types: list[str]
    actions: list[str]
    actors: list[AuditActorOption]
    scope: str
