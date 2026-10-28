"""Enseignants d'une matière : liste ordonnée, validée et synchronisée.

`subjects.teacher_id` suit toujours le premier enseignant de la liste, pour les
lecteurs qui n'ont pas encore migré (voir la migration 0087).
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditAction, audit_log
from app.core.exceptions import BusinessValidationError, NotFoundError
from app.models.academic import Subject
from app.models.user import TeacherProfile
from app.repositories import class_subject_teacher_repository as class_repo
from app.repositories import subject_teacher_repository as repo
from app.schemas.subject_teachers import (
    SubjectSlotCount,
    SubjectSlotCountsResponse,
    SubjectTeacherRef,
)

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


async def ensure_teacher_kept(db: AsyncSession, *, teacher_id: int, subject_id: int) -> None:
    """Refuse un créneau pour un enseignant qui n'enseigne pas la matière.

    Sans enseignant retenu pour la matière, aucune restriction : la matière n'est pas
    encore répartie. Le nom n'est lu qu'en cas de refus.
    """
    kept = await repo.list_teacher_ids(db, subject_id)
    if not kept or teacher_id in kept:
        return
    teacher = await db.get(TeacherProfile, teacher_id)
    subject = await db.get(Subject, subject_id)
    nom_enseignant = (teacher.display_name if teacher else "") or f"L'enseignant #{teacher_id}"
    nom_matiere = subject.name if subject else f"#{subject_id}"
    raise BusinessValidationError(
        f"{nom_enseignant} n'enseigne pas « {nom_matiere} » dans ce niveau."
    )


async def _journaliser_retraits(
    db: AsyncSession, retraits: dict[int, list[int]], *, actor: int | None
) -> None:
    """Une entrée d'audit par matière dont des choix de classe ont été retirés."""
    for subject_id, class_ids in retraits.items():
        subject = await db.get(Subject, subject_id)
        await audit_log(
            db,
            entity_type="subject",
            action=AuditAction.UPDATE,
            user_id=actor,
            entity_id=subject_id,
            old_values={"class_teacher_choices_removed": sorted(class_ids)},
            new_values={"class_teacher_choices_removed": []},
            subject_label=subject.name if subject else None,
        )


async def set_subject_teachers(
    db: AsyncSession, subject: Subject, ordered_ids: list[int], *, actor: int | None = None
) -> list[int]:
    """Remplace les enseignants de la matière par `ordered_ids` (déjà validés).

    Retire les choix de classe devenus orphelins et les journalise. Rend la liste
    précédente, pour que l'appelant puisse journaliser le changement.
    Ne commite pas : l'appelant garde la transaction.
    """
    previous = await repo.list_teacher_ids(db, subject.id)
    await repo.delete_links(db, subject.id)
    await repo.add_links(db, subject.id, ordered_ids)
    subject.teacher_id = ordered_ids[0] if ordered_ids else None
    await db.flush()
    # La collection chargée avant l'écriture ne doit pas survivre à l'écriture.
    db.expire(subject, ["teacher_links"])
    retraits = await class_repo.purge_orphan_teachers(db, subject.id, ordered_ids)
    await _journaliser_retraits(db, retraits, actor=actor)
    return previous


async def replace_teachers(
    db: AsyncSession, subject: Subject, ordered_ids: list[int], *, actor: int
) -> None:
    """Remplace la liste et journalise l'ancienne et la nouvelle, si elle change."""
    previous = await set_subject_teachers(db, subject, ordered_ids, actor=actor)
    if previous == ordered_ids:
        return
    await audit_log(
        db,
        entity_type="subject",
        action=AuditAction.UPDATE,
        user_id=actor,
        entity_id=subject.id,
        old_values={"teacher_ids": previous},
        new_values={"teacher_ids": ordered_ids},
        subject_label=subject.name,
    )


async def unlink_teacher(db: AsyncSession, teacher_id: int, *, actor: int | None = None) -> None:
    """Retire un enseignant de toutes ses matières, et de tous ses choix de classe.

    Le suivant de chaque matière prend la première place.
    """
    subject_ids = await repo.subject_ids_for_teacher(db, teacher_id)
    await repo.delete_links_for_teacher(db, teacher_id)
    retraits = await class_repo.purge_choices_of_teacher(db, teacher_id)
    await repo.resync_first_teacher(db, subject_ids)
    await _journaliser_retraits(db, retraits, actor=actor)


def teacher_refs(subject: Subject) -> list[SubjectTeacherRef]:
    return [
        SubjectTeacherRef(id=link.teacher.id, full_name=link.teacher.display_name)
        for link in subject.teacher_links
    ]


async def slot_counts_for_subject(db: AsyncSession, subject_id: int) -> SubjectSlotCountsResponse:
    """Réponse de la route des créneaux par enseignant."""
    if await db.get(Subject, subject_id) is None:
        raise NotFoundError("Subject", subject_id)
    rows = await repo.count_slots_by_teacher(db, subject_id)
    return SubjectSlotCountsResponse(
        counts=[SubjectSlotCount(teacher_id=tid, slots=n) for tid, n in rows]
    )
