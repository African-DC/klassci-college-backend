"""Enseignants d'une matière : liste ordonnée, validée et synchronisée.

`subjects.teacher_id` suit toujours le premier enseignant de la liste, pour les
lecteurs qui n'ont pas encore migré (voir la migration 0087).
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessValidationError, NotFoundError
from app.models.academic import Subject
from app.repositories import subject_teacher_repository as repo
from app.schemas.subject_teachers import SubjectSlotCountsResponse

MAX_TEACHERS_PER_SUBJECT = 30


async def validate_teacher_ids(db: AsyncSession, teacher_ids: list[int]) -> list[int]:
    """Dédoublonne en gardant le premier rang, puis vérifie les identifiants. N'écrit rien."""
    ordered = list(dict.fromkeys(teacher_ids))
    if len(ordered) > MAX_TEACHERS_PER_SUBJECT:
        raise BusinessValidationError(
            f"Une matière ne peut pas avoir plus de {MAX_TEACHERS_PER_SUBJECT} enseignants."
        )
    if ordered:
        found = await repo.find_existing_teacher_ids(db, ordered)
        missing = [tid for tid in ordered if tid not in found]
        if missing:
            ids = ", ".join(str(tid) for tid in missing)
            raise BusinessValidationError(f"Enseignant(s) introuvable(s) : {ids}.")
    return ordered


async def set_subject_teachers(
    db: AsyncSession, subject: Subject, ordered_ids: list[int]
) -> list[int]:
    """Remplace les enseignants de la matière par `ordered_ids` (déjà validés).

    Rend la liste précédente, pour que l'appelant puisse journaliser le changement.
    Ne commite pas : l'appelant garde la transaction.
    """
    previous = await repo.list_teacher_ids(db, subject.id)
    await repo.delete_links(db, subject.id)
    await repo.add_links(db, subject.id, ordered_ids)
    subject.teacher_id = ordered_ids[0] if ordered_ids else None
    await db.flush()
    # La collection chargée avant l'écriture ne doit pas survivre à l'écriture.
    db.expire(subject, ["teacher_links"])
    return previous


async def detach_teacher(db: AsyncSession, teacher_id: int) -> list[int]:
    """Retire un enseignant de toutes ses matières ; rend les matières touchées."""
    subject_ids = await repo.subject_ids_for_teacher(db, teacher_id)
    await repo.delete_links_for_teacher(db, teacher_id)
    return subject_ids


async def resync_first_teacher(db: AsyncSession, subject_ids: list[int]) -> None:
    await repo.resync_first_teacher(db, subject_ids)


async def slot_counts_for_subject(db: AsyncSession, subject_id: int) -> SubjectSlotCountsResponse:
    """Réponse de la route des créneaux par enseignant."""
    if await db.get(Subject, subject_id) is None:
        raise NotFoundError("Subject", subject_id)
    return SubjectSlotCountsResponse(counts=await repo.count_slots_by_teacher(db, subject_id))
