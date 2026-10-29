"""Small cohesive incident workflow; every operation receives a tenant-scoped DB session."""
import logging
import secrets
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.datetimes import utcnow_naive
from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.models.support_incident import SupportIncident, SupportIncidentEvent
from app.schemas.support_incident import IncidentCreate, IncidentOut, IncidentPage, IncidentReply, IncidentUpdate

logger = logging.getLogger(__name__)

def _as_output(item: SupportIncident, events: list[SupportIncidentEvent] | None = None) -> IncidentOut:
    return IncidentOut.model_validate(item).model_copy(
        update={"events": [__import__("app.schemas.support_incident", fromlist=["IncidentEventOut"]).IncidentEventOut.model_validate(e) for e in events or []]}
    )

async def create(db: AsyncSession, data: IncidentCreate, actor_id: int) -> IncidentOut:
    item = SupportIncident(
        title=data.title.strip(), description=data.description.strip(),
        reference=data.reference.upper() if data.reference else None,
        source=data.source, created_by=actor_id,
    )
    db.add(item)
    await db.flush()
    db.add(SupportIncidentEvent(incident_id=item.id, actor_id=actor_id,
                                actor_kind="school", message="Signalement créé"))
    await db.commit()
    await db.refresh(item)
    return _as_output(item)

async def list_page(db: AsyncSession, *, actor_id: int | None, reference: str | None,
                    status: str | None, page: int, size: int) -> IncidentPage:
    stmt = select(SupportIncident)
    if actor_id is not None:
        stmt = stmt.where(SupportIncident.created_by == actor_id)
    if reference:
        stmt = stmt.where(SupportIncident.reference == reference.upper())
    if status:
        stmt = stmt.where(SupportIncident.status == status)
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (await db.execute(stmt.order_by(SupportIncident.created_at.desc(), SupportIncident.id.desc())
                             .offset((page - 1)*size).limit(size))).scalars().all()
    return IncidentPage(items=[_as_output(row) for row in rows], total=total, page=page, size=size)

async def get(db: AsyncSession, incident_id: str, *, actor_id: int | None) -> IncidentOut:
    item = await db.get(SupportIncident, incident_id)
    if item is None:
        raise NotFoundError("Incident", incident_id)
    if actor_id is not None and item.created_by != actor_id:
        # Hide existence of another user's issue.
        raise NotFoundError("Incident", incident_id)
    events = (await db.execute(select(SupportIncidentEvent).where(SupportIncidentEvent.incident_id == incident_id)
                                .order_by(SupportIncidentEvent.created_at, SupportIncidentEvent.id))).scalars().all()
    return _as_output(item, list(events))

async def reply(db: AsyncSession, incident_id: str, data: IncidentReply,
                *, actor_id: int, actor_kind: str, owner_only: bool) -> IncidentOut:
    item = await db.get(SupportIncident, incident_id)
    if item is None or (owner_only and item.created_by != actor_id):
        raise NotFoundError("Incident", incident_id)
    if item.status == "closed":
        raise PermissionDeniedError("Incident fermé")
    db.add(SupportIncidentEvent(incident_id=incident_id, actor_id=actor_id if actor_kind == "school" else None,
                                actor_kind=actor_kind, message=data.message.strip()))
    if actor_kind == "school" and item.status == "waiting":
        item.status = "in_progress"
    await db.commit()
    return await get(db, incident_id, actor_id=actor_id if owner_only else None)

async def update(db: AsyncSession, incident_id: str, data: IncidentUpdate) -> IncidentOut:
    item = await db.get(SupportIncident, incident_id)
    if item is None:
        raise NotFoundError("Incident", incident_id)
    item.status = data.status
    if data.priority is not None:
        item.priority = data.priority
    item.resolved_at = utcnow_naive() if data.status == "resolved" else None
    db.add(SupportIncidentEvent(incident_id=incident_id, actor_kind="support",
                                status=data.status, message=data.message.strip() if data.message else None))
    await db.commit()
    return await get(db, incident_id, actor_id=None)

async def capture_unexpected(reference: str, tenant_id: str) -> None:
    """Best effort: an unavailable database must NEVER hide the original 500."""
    from app.core.database import _get_session_factory
    factory = await _get_session_factory(tenant_id)
    async with factory() as db:
        item = SupportIncident(reference=reference, title="Erreur serveur",
                               description="Incident détecté automatiquement", source="backend", priority="high")
        db.add(item)
        await db.commit()
