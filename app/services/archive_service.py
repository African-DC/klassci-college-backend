"""Archivage, restauration et suppression définitive.

Trois gestes, trois niveaux d'engagement :

- **archiver** : la fiche quitte les écrans, rien n'est détruit, on peut
  revenir dessus le lendemain ;
- **restaurer** : elle revient, sans condition ;
- **supprimer définitivement** : irréversible, réservé à l'administrateur, et
  seulement depuis la corbeille — on ne détruit jamais une fiche qu'on vient
  de voir dans une liste.

Chaque geste destructeur exige un motif, part au journal d'audit avec
l'identité figée de son auteur, et déclenche un courriel. Un mail sort du
logiciel : si quelqu'un efface une trace, il n'efface pas une boîte de
réception.
"""

import logging
from dataclasses import dataclass
from typing import Protocol

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditAction, audit_log
from app.core.datetimes import utcnow_naive

logger = logging.getLogger(__name__)

# Un motif d'un mot ne dit rien. Assez court pour ne pas décourager, assez
# long pour interdire « ok » ou « test ».
MIN_REASON_LENGTH = 10


class Archivable(Protocol):
    id: int
    archived_at: object
    archived_by: object
    archive_reason: object


@dataclass(frozen=True, slots=True)
class ArchiveOutcome:
    """Ce qui s'est passé, pour le journal et pour le courriel."""

    entity_type: str
    entity_id: int
    label: str
    reason: str
    permanent: bool


def _clean_reason(reason: str | None) -> str:
    cleaned = (reason or "").strip()
    if len(cleaned) < MIN_REASON_LENGTH:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Indiquez le motif en {MIN_REASON_LENGTH} caractères au moins. "
                "Il figurera dans le journal et dans le courriel envoyé à la direction."
            ),
        )
    return cleaned


async def archive(
    db: AsyncSession,
    entity: Archivable,
    *,
    entity_type: str,
    label: str,
    reason: str | None,
    actor_id: int,
) -> ArchiveOutcome:
    """Retire la fiche des écrans sans rien détruire."""
    if entity.archived_at is not None:
        raise HTTPException(status_code=409, detail=f"{label} est déjà dans la corbeille.")

    cleaned = _clean_reason(reason)
    entity.archived_at = utcnow_naive()
    entity.archived_by = actor_id
    entity.archive_reason = cleaned

    await audit_log(
        db,
        entity_type=entity_type,
        action=AuditAction.UPDATE,
        user_id=actor_id,
        entity_id=entity.id,
        new_values={"archived": True, "label": label},
        notes=cleaned,
    )
    await db.commit()
    logger.info("Archivage %s %s par %s : %s", entity_type, entity.id, actor_id, cleaned)
    return ArchiveOutcome(entity_type, entity.id, label, cleaned, permanent=False)


async def restore(
    db: AsyncSession,
    entity: Archivable,
    *,
    entity_type: str,
    label: str,
    actor_id: int,
) -> None:
    """Sort la fiche de la corbeille.

    Aucun motif demandé : restaurer répare, ça ne détruit rien. Exiger une
    justification pour revenir en arrière découragerait de corriger une
    erreur, ce qui est exactement l'inverse du but.
    """
    if entity.archived_at is None:
        raise HTTPException(status_code=409, detail=f"{label} n'est pas dans la corbeille.")

    entity.archived_at = None
    entity.archived_by = None
    entity.archive_reason = None

    await audit_log(
        db,
        entity_type=entity_type,
        action=AuditAction.UPDATE,
        user_id=actor_id,
        entity_id=entity.id,
        new_values={"archived": False, "label": label},
    )
    await db.commit()


def ensure_archived_first(entity: Archivable, *, label: str) -> None:
    """Interdit la suppression définitive d'une fiche encore visible.

    Le passage par la corbeille est ce qui laisse le temps de se raviser. Le
    court-circuiter transformerait un clic malheureux en perte définitive.
    """
    if entity.archived_at is None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"{label} doit d'abord être placé dans la corbeille. "
                "La suppression définitive ne s'y fait qu'ensuite."
            ),
        )


async def record_permanent_deletion(
    db: AsyncSession,
    *,
    entity_type: str,
    entity_id: int,
    label: str,
    reason: str | None,
    actor_id: int,
    carried_away: list[dict[str, object]] | None = None,
) -> ArchiveOutcome:
    """Journalise la suppression définitive avant qu'elle n'ait lieu.

    Écrit avant, délibérément : une fois la fiche partie, on ne peut plus
    relire son nom pour l'inscrire au journal.
    """
    cleaned = _clean_reason(reason)
    await audit_log(
        db,
        entity_type=entity_type,
        action=AuditAction.DELETE,
        user_id=actor_id,
        entity_id=entity_id,
        old_values={"label": label},
        new_values={"permanent": True, "emporte": carried_away or []},
        notes=cleaned,
    )
    logger.warning(
        "Suppression definitive %s %s par %s : %s", entity_type, entity_id, actor_id, cleaned
    )
    return ArchiveOutcome(entity_type, entity_id, label, cleaned, permanent=True)
