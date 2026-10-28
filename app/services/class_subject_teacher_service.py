"""Enseignant retenu par classe et par matière.

Règle de résolution, pour une matière de la classe :
1. le choix explicite de la classe, s'il désigne encore un enseignant retenu
   pour la matière (`explicit`) ;
2. sinon l'unique enseignant retenu pour la matière (`single`) ;
3. sinon rien (`none`) : la classe doit choisir, et aucun nom n'est deviné.
"""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditAction, audit_log
from app.core.exceptions import BusinessValidationError, NotFoundError
from app.models.academic import Class, Subject
from app.models.user import TeacherProfile
from app.repositories import class_subject_teacher_repository as repo
from app.schemas.class_subject_teachers import ClassSubjectTeacherAssignment, Source
from app.schemas.subject_teachers import SubjectTeacherRef
from app.services.class_subjects import subjects_for_class
from app.services.subject_teachers import ensure_teacher_kept


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


def _eligible_refs(subject: Subject) -> list[SubjectTeacherRef]:
    return [
        SubjectTeacherRef(
            id=link.teacher_id,
            full_name=(link.teacher.display_name if link.teacher else "")
            or f"L'enseignant #{link.teacher_id}",
        )
        for link in subject.teacher_links
    ]


def resolve_one(eligible_ids: list[int], assigned: int | None) -> tuple[int | None, Source]:
    """Enseignant résolu et sa source, pour une matière. Pure."""
    if assigned is not None and assigned in eligible_ids:
        return assigned, "explicit"
    if len(eligible_ids) == 1:
        return eligible_ids[0], "single"
    return None, "none"


async def load_class_or_404(db: AsyncSession, class_id: int) -> Class:
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


async def class_teacher_names(db: AsyncSession, class_id: int) -> dict[int, str]:
    """subject_id -> nom de l'enseignant résolu, pour les bulletins et synthèses.

    Une matière sans enseignant résolu n'a pas de nom : aucun repli n'est inventé.
    Une classe inconnue donne un dictionnaire vide.
    """
    cls = await db.get(Class, class_id)
    if cls is None:
        return {}
    return {
        e.subject.id: e.resolved_name
        for e in await resolve_class_teachers(db, cls)
        if e.resolved_name
    }


async def _matiere_nom(db: AsyncSession, subject_id: int) -> str:
    subject = await db.get(Subject, subject_id)
    return subject.name if subject is not None else f"#{subject_id}"


async def _verifier_retenu(db: AsyncSession, subject: Subject, teacher_id: int) -> None:
    """Refuse un enseignant qui n'est pas retenu pour la matière. N'écrit rien."""
    eligible = _eligible_refs(subject)
    if teacher_id in {t.id for t in eligible}:
        return
    nom = next((t.full_name for t in eligible if t.id == teacher_id), None)
    if nom is None:
        teacher = await db.get(TeacherProfile, teacher_id)
        nom = (teacher.display_name if teacher else "") or f"L'enseignant #{teacher_id}"
    raise BusinessValidationError(
        f"« {nom} » n'est pas retenu pour la matière « {subject.name} » dans ce niveau."
    )


async def save_class_teachers(
    db: AsyncSession,
    class_id: int,
    assignments: list[ClassSubjectTeacherAssignment],
    *,
    actor: int,
) -> tuple[Class, list[ClassSubjectTeacherEntry]]:
    """Enregistre les choix de la classe, puis rend la classe et la résolution fraîches.

    Toute la liste est validée avant la moindre écriture.
    """
    cls = await load_class_or_404(db, class_id)
    by_subject = {s.id: s for s in await subjects_for_class(db, cls)}
    wanted: dict[int, int | None] = {}
    for item in assignments:
        subject = by_subject.get(item.subject_id)
        if subject is None:
            nom = await _matiere_nom(db, item.subject_id)
            raise BusinessValidationError(
                f"La matière « {nom} » n'est pas enseignée dans cette classe."
            )
        if item.teacher_id is not None:
            await _verifier_retenu(db, subject, item.teacher_id)
        wanted[subject.id] = item.teacher_id

    previous = await repo.explicit_teachers_for_class(db, class_id)
    await repo.apply_class_teachers(db, class_id, wanted)
    current = dict(previous)
    for subject_id, teacher_id in wanted.items():
        if teacher_id is None:
            current.pop(subject_id, None)
        else:
            current[subject_id] = teacher_id
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
    cls = await load_class_or_404(db, class_id)
    return cls, await resolve_class_teachers(db, cls)


async def ensure_slot_teacher(
    db: AsyncSession, *, class_id: int, subject_id: int, teacher_id: int
) -> None:
    """Refuse un créneau dont l'enseignant n'est pas celui que la classe a choisi.

    L'enseignant doit d'abord être retenu pour la matière. Si la classe a choisi
    un enseignant pour cette matière, seul celui-ci peut y être planifié.
    """
    await ensure_teacher_kept(db, teacher_id=teacher_id, subject_id=subject_id)
    chosen = (await repo.explicit_teachers_for_class(db, class_id)).get(subject_id)
    if chosen is None or chosen == teacher_id:
        return
    teacher = await db.get(TeacherProfile, chosen)
    subject = await db.get(Subject, subject_id)
    nom = (teacher.display_name if teacher else "") or f"l'enseignant #{chosen}"
    matiere = subject.name if subject else f"#{subject_id}"
    raise BusinessValidationError(
        f"Dans cette classe, « {matiere} » est confiée à {nom}. "
        "Changez l'enseignant dans « Enseignants de la classe » pour en planifier un autre."
    )
