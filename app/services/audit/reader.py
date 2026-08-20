"""Compose les pages du journal.

Le cloisonnement se décide une fois, dans `_scope`, et vaut pour la liste
comme pour les filtres proposés : un comptable ne doit pas voir dans le menu
déroulant des entités que la liste lui refusera ensuite.
"""

from datetime import date

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditAction
from app.repositories import audit_repository as repo
from app.repositories.audit_repository import AuditFilters
from app.schemas.audit import (
    AuditActorOption,
    AuditEntryResponse,
    AuditFiltersResponse,
    AuditListResponse,
)
from app.services.audit._scope import visible_entity_types


def _scope(full_access: bool, financial_access: bool) -> frozenset[str] | None:
    allowed = visible_entity_types(full_access=full_access, financial_access=financial_access)
    if allowed is not None and not allowed:
        # Aucune entité visible : c'est un refus, pas une page vide. Une liste
        # vide laisserait croire qu'il ne s'est rien passé.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Vous n'avez pas accès au journal d'audit.",
        )
    return allowed


async def list_journal(
    db: AsyncSession,
    *,
    full_access: bool,
    financial_access: bool,
    entity_type: str | None = None,
    entity_id: int | None = None,
    action: str | None = None,
    user_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    search: str | None = None,
    page: int = 1,
    size: int = 50,
) -> AuditListResponse:
    allowed = _scope(full_access, financial_access)
    rows, total = await repo.list_entries(
        db,
        AuditFilters(
            entity_types=allowed,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            user_id=user_id,
            date_from=date_from,
            date_to=date_to,
            search=search,
        ),
        page=page,
        size=size,
    )

    names = await repo.actor_names(db, {r.user_id for r in rows if r.user_id is not None})

    return AuditListResponse(
        items=[
            AuditEntryResponse(
                id=row.id,
                created_at=row.created_at,
                action=str(row.action.value if hasattr(row.action, "value") else row.action),
                entity_type=row.entity_type,
                entity_id=row.entity_id,
                user_id=row.user_id,
                actor_name=names.get(row.user_id) if row.user_id is not None else None,
                actor_email=row.actor_email,
                actor_role=row.actor_role,
                ip_address=row.ip_address,
                notes=row.notes,
                old_values=row.old_values,
                new_values=row.new_values,
            )
            for row in rows
        ],
        total=total,
        page=page,
        size=size,
    )


async def get_filters(
    db: AsyncSession, *, full_access: bool, financial_access: bool
) -> AuditFiltersResponse:
    allowed = _scope(full_access, financial_access)
    entity_types = await repo.distinct_entity_types(db, allowed)
    actors = await repo.distinct_actors(db, allowed)
    names = await repo.actor_names(db, {uid for uid, _ in actors})

    return AuditFiltersResponse(
        entity_types=entity_types,
        actions=[a.value for a in AuditAction],
        actors=sorted(
            (
                AuditActorOption(user_id=uid, name=names.get(uid), email=email)
                for uid, email in actors
            ),
            key=lambda a: (a.name or a.email or "").lower(),
        ),
        scope="full" if allowed is None else "financial",
    )
