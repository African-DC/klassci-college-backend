"""Enseignant retenu par classe et par matière.

Règle de résolution, pour une matière de la classe :
1. le choix explicite de la classe, s'il désigne encore un enseignant retenu
   pour la matière (`explicit`) ;
2. sinon l'unique enseignant retenu pour la matière (`single`) ;
3. sinon rien (`none`) : la classe doit choisir.
"""

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditAction, audit_log
from app.core.exceptions import BusinessValidationError, NotFoundError
from app.models.academic import Class, Subject
from app.models.subject_teacher import SubjectTeacher
from app.models.user import TeacherProfile
from app.repositories import class_subject_teacher_repository as repo
from app.schemas.class_subject_teachers import ClassSubjectTeacherAssignment
from app.schemas.subject_teachers import SubjectTeacherRef
from app.services.class_subjects import subject_applies_to_class, subjects_for_class

Source = Literal["explicit", "single", "none"]


@dataclass(frozen=True)
class ClassSubjectTeacherEntry:
    subject: Subject
    eligible: list[SubjectTeacherRef]
    assigned_teacher_id: int | None
    resolved_teacher_id: int | None
    source: Source

    @property
    def resolved_name(self) -> str | None:
        return next((t.full_name for t in self.eligible if t.id == self.resolved_teacher_id), None)


def _full_name(teacher: TeacherProfile | None, teacher_id: int) -> str:
    if teacher is None:
        return f"L'enseignant #{teacher_id}"
    return f"{teacher.first_name} {teacher.last_name}".strip() or f"L'enseignant #{teacher_id}"


def _eligible_refs(subject: Subject) -> list[SubjectTeacherRef]:
    return [
        SubjectTeacherRef(id=link.teacher_id, full_name=_full_name(link.teacher, link.teacher_id))
        for link in subject.teacher_links
    ]


def resolve_one(eligible_ids: list[int], assigned: int | None) -> tuple[int | None, Source]:
    """Enseignant résolu et sa source, pour une matière. Pure."""
    if assigned is not None and assigned in eligible_ids:
        return assigned, "explicit"
    if len(eligible_ids) == 1:
        return eligible_ids[0], "single"
    return None, "none"


async def _load_class(db: AsyncSession, class_id: int) -> Class:
    cls = await db.get(Class, class_id)
    if cls is None:
        raise NotFoundError("Class", class_id)
    return cls


async def resolve_class_teachers(db: AsyncSession, cls: Class) -> list[ClassSubjectTeacherEntry]:
    """Une entrée par matière de la classe, avec son enseignant résolu."""
    subjects = await subjects_for_class(db, cls)
    explicit = await repo.explicit_teachers_for_class(db, cls.id)
    entries = []
    for subject in subjects:
        eligible = _eligible_refs(subject)
        assigned = explicit.get(subject.id)
        resolved, source = resolve_one([t.id for t in eligible], assigned)
        entries.append(
            ClassSubjectTeacherEntry(
                subject=subject,
                eligible=eligible,
                assigned_teacher_id=assigned,
                resolved_teacher_id=resolved,
                source=source,
            )
        )
    return entries


async def resolved_teacher_map(db: AsyncSession, class_id: int) -> dict[int, int]:
    """subject_id -> teacher_id, pour les matières dont l'enseignant est résolu."""
    cls = await _load_class(db, class_id)
    return {
        e.subject.id: e.resolved_teacher_id
        for e in await resolve_class_teachers(db, cls)
        if e.resolved_teacher_id is not None
    }


async def class_teacher_names(db: AsyncSession, class_id: int) -> dict[int, str]:
    """subject_id -> nom de l'enseignant de la classe, pour les bulletins et synthèses.

    Repli sur le premier enseignant retenu quand la classe n'a rien résolu.
    Une classe inconnue donne un dictionnaire vide.
    """
    cls = await db.get(Class, class_id)
    if cls is None:
        return {}
    names: dict[int, str] = {}
    for entry in await resolve_class_teachers(db, cls):
        name = entry.resolved_name
        if name is None and entry.eligible:
            name = entry.eligible[0].full_name
        if name:
            names[entry.subject.id] = name
    return names


async def _matiere_nom(db: AsyncSession, subject_id: int) -> str:
    subject = await db.get(Subject, subject_id)
    return subject.name if subject is not None else f"#{subject_id}"


async def save_class_teachers(
    db: AsyncSession,
    class_id: int,
    assignments: list[ClassSubjectTeacherAssignment],
    *,
    actor: int,
) -> list[ClassSubjectTeacherEntry]:
    """Enregistre les choix de la classe, puis renvoie la résolution fraîche."""
    cls = await _load_class(db, class_id)
    by_subject = {s.id: s for s in await subjects_for_class(db, cls)}
    previous = await repo.explicit_teachers_for_class(db, class_id)
    current = dict(previous)

    for item in assignments:
        subject = by_subject.get(item.subject_id)
        if subject is None:
            nom = await _matiere_nom(db, item.subject_id)
            raise BusinessValidationError(
                f"La matière « {nom} » n'est pas enseignée dans cette classe."
            )
        if item.teacher_id is None:
            await repo.set_class_teacher(db, class_id, subject.id, None)
            current.pop(subject.id, None)
            continue
        eligible = _eligible_refs(subject)
        if item.teacher_id not in {t.id for t in eligible}:
            nom = next((t.full_name for t in eligible if t.id == item.teacher_id), None)
            if nom is None:
                nom = _full_name(await db.get(TeacherProfile, item.teacher_id), item.teacher_id)
            raise BusinessValidationError(
                f"« {nom} » n'est pas retenu pour la matière « {subject.name} » dans ce niveau."
            )
        await repo.set_class_teacher(db, class_id, subject.id, item.teacher_id)
        current[subject.id] = item.teacher_id

    if current != previous:
        await audit_log(
            db,
            entity_type="class",
            action=AuditAction.UPDATE,
            user_id=actor,
            entity_id=class_id,
            old_values={"subject_teachers": {str(k): v for k, v in previous.items()}},
            new_values={"subject_teachers": {str(k): v for k, v in current.items()}},
            subject_label=cls.name,
        )
    await db.commit()
    cls = await _load_class(db, class_id)
    return await resolve_class_teachers(db, cls)


async def purge_orphan_class_teachers(
    db: AsyncSession, subject_id: int, kept_teacher_ids: list[int]
) -> None:
    """Appelé quand la liste d'enseignants d'une matière change. Ne commite pas."""
    await repo.purge_orphan_teachers(db, subject_id, kept_teacher_ids)


async def teacher_weekly_hours(db: AsyncSession, teacher_id: int) -> int:
    """Heures par semaine : somme des matières résolues vers cet enseignant, par classe."""
    subjects = await repo.subjects_taught_by(db, teacher_id)
    if not subjects:
        return 0
    level_ids = {s.level_id for s in subjects if s.level_id is not None}
    classes = await repo.classes_for_levels(db, level_ids)
    explicit = await repo.explicit_teachers_for_subjects(db, [s.id for s in subjects])

    total = 0
    for subject in subjects:
        eligible_ids = [link.teacher_id for link in subject.teacher_links]
        for cls in classes:
            if not subject_applies_to_class(subject, cls):
                continue
            resolved, _ = resolve_one(eligible_ids, explicit.get((cls.id, subject.id)))
            if resolved == teacher_id:
                total += subject.hours_per_week
    return total


async def verifier_enseignant_retenu(
    db: AsyncSession, *, teacher_id: int, subject_id: int, nom_enseignant: str
) -> None:
    """Refuse un créneau pour un enseignant qui n'enseigne pas la matière.

    Sans enseignant retenu pour la matière, aucune restriction : la matière n'est pas
    encore répartie.
    """
    retenus = (
        (
            await db.execute(
                select(SubjectTeacher.teacher_id).where(SubjectTeacher.subject_id == subject_id)
            )
        )
        .scalars()
        .all()
    )
    if not retenus or teacher_id in retenus:
        return
    nom_matiere = (
        await db.execute(select(Subject.name).where(Subject.id == subject_id))
    ).scalar_one_or_none() or f"#{subject_id}"
    raise BusinessValidationError(
        f"{nom_enseignant} n'enseigne pas « {nom_matiere} » dans ce niveau."
    )
