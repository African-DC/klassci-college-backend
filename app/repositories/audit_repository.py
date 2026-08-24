"""Lecture du journal d'audit.

Le nom affichable de l'auteur n'est pas stocké dans `audit_logs` : il vit sur
les fiches (personnel, enseignant, élève, parent). On le résout par page —
quelques dizaines d'identifiants, quatre requêtes — plutôt qu'en greffant
quatre jointures externes sur une table qui grossit à chaque geste de la
journée.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditLog
from app.models.user import Parent, StaffProfile, Student, TeacherProfile

# Chaque fiche portant un nom, avec la colonne qui pointe vers le compte.
_NAME_SOURCES = (StaffProfile, TeacherProfile, Student, Parent)


@dataclass(frozen=True, slots=True)
class AuditFilters:
    entity_types: frozenset[str] | None = None
    entity_type: str | None = None
    entity_id: int | None = None
    action: str | None = None
    user_id: int | None = None
    date_from: date | None = None
    date_to: date | None = None
    search: str | None = None


def _apply(stmt: Select, filters: AuditFilters) -> Select:
    if filters.entity_types is not None:
        # Un ensemble vide veut dire « rien de visible » : on le dit en SQL
        # plutôt que de laisser passer la requête sans clause.
        stmt = stmt.where(AuditLog.entity_type.in_(filters.entity_types or {"__none__"}))
    if filters.entity_type:
        stmt = stmt.where(AuditLog.entity_type == filters.entity_type)
    if filters.entity_id is not None:
        stmt = stmt.where(AuditLog.entity_id == filters.entity_id)
    if filters.action:
        stmt = stmt.where(AuditLog.action == filters.action)
    if filters.user_id is not None:
        stmt = stmt.where(AuditLog.user_id == filters.user_id)
    if filters.date_from:
        stmt = stmt.where(AuditLog.created_at >= datetime.combine(filters.date_from, time.min))
    if filters.date_to:
        stmt = stmt.where(AuditLog.created_at <= datetime.combine(filters.date_to, time.max))
    if filters.search:
        like = f"%{filters.search.strip()}%"
        stmt = stmt.where(
            or_(
                AuditLog.actor_email.like(like),
                AuditLog.entity_type.like(like),
                AuditLog.notes.like(like),
            )
        )
    return stmt


async def list_entries(
    db: AsyncSession, filters: AuditFilters, *, page: int, size: int
) -> tuple[Sequence[AuditLog], int]:
    base = _apply(select(AuditLog), filters)
    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    rows = (
        (
            await db.execute(
                base.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
                .offset((page - 1) * size)
                .limit(size)
            )
        )
        .scalars()
        .all()
    )
    return rows, int(total)


async def actor_names(db: AsyncSession, user_ids: set[int]) -> dict[int, str]:
    """Nom affichable par compte, cherché sur chaque type de fiche."""
    if not user_ids:
        return {}

    names: dict[int, str] = {}
    for model in _NAME_SOURCES:
        rows = await db.execute(
            select(model.user_id, model.first_name, model.last_name).where(
                model.user_id.in_(user_ids)
            )
        )
        for user_id, first_name, last_name in rows.all():
            if user_id is not None and user_id not in names:
                names[int(user_id)] = f"{first_name} {last_name}".strip()
    return names


async def distinct_entity_types(db: AsyncSession, allowed: frozenset[str] | None) -> list[str]:
    """Entités réellement présentes dans le journal, pour ne proposer que des
    filtres qui donnent des résultats."""
    stmt = select(AuditLog.entity_type).distinct().order_by(AuditLog.entity_type)
    if allowed is not None:
        stmt = stmt.where(AuditLog.entity_type.in_(allowed or {"__none__"}))
    return [str(row[0]) for row in (await db.execute(stmt)).all()]


async def distinct_actors(
    db: AsyncSession, allowed: frozenset[str] | None
) -> list[tuple[int, str | None]]:
    """Comptes ayant laissé une trace visible, pour le filtre « par personne »."""
    stmt = (
        select(AuditLog.user_id, func.max(AuditLog.actor_email))
        .where(AuditLog.user_id.isnot(None))
        .group_by(AuditLog.user_id)
    )
    if allowed is not None:
        stmt = stmt.where(AuditLog.entity_type.in_(allowed or {"__none__"}))
    return [(int(uid), email) for uid, email in (await db.execute(stmt)).all()]
