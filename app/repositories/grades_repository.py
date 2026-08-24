"""Repository notes — accès DB pour Evaluation, Grade et Bulletin."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, NamedTuple

from sqlalchemy import Select, case, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.enrollment import Enrollment
from app.models.grade import (
    COUNTED_GRADE_STATUSES,
    STICKY_GRADE_STATUSES,
    Bulletin,
    Evaluation,
    Grade,
    GradeStatus,
    Mention,
)
from app.models.user import Student

# ---------------------------------------------------------------------------
# Helpers internes
# ---------------------------------------------------------------------------


def _compute_mention(avg: Decimal | None) -> str | None:
    if avg is None:
        return None
    if avg >= 16:
        return Mention.TRES_BIEN.value
    if avg >= 14:
        return Mention.BIEN.value
    if avg >= 12:
        return Mention.ASSEZ_BIEN.value
    if avg >= 10:
        return Mention.PASSABLE.value
    return Mention.MEDIOCRE.value


def _student_full_name(s: Student) -> str:
    return f"{s.first_name} {s.last_name}"


# ---------------------------------------------------------------------------
# Students d'une classe
# ---------------------------------------------------------------------------


async def get_students_for_class(
    db: AsyncSession, class_id: int, academic_year_id: int
) -> list[Student]:
    """Retourne les élèves inscrits (valide) dans une classe pour une année."""
    stmt = (
        select(Student)
        .join(Enrollment, Enrollment.student_id == Student.id)
        .where(
            Enrollment.class_id == class_id,
            Enrollment.academic_year_id == academic_year_id,
            Enrollment.status == "valide",
        )
        .order_by(Student.last_name, Student.first_name)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


class EvaluationGradeCounts(NamedTuple):
    """Compteurs d'une évaluation, comptés en SQL et non en mémoire."""

    total: int
    graded: int


NO_GRADES = EvaluationGradeCounts(total=0, graded=0)


def _eval_options() -> list[Any]:
    """Chargement complet, notes comprises.

    Réservé aux lectures qui exploitent réellement `Evaluation.grades` :
    la fiche d'une évaluation et le relevé de notes PDF. La liste
    paginée, elle, ne rapatrie jamais les notes (cf. `_eval_light_options`).
    """
    return [
        selectinload(Evaluation.subject),
        selectinload(Evaluation.class_),
        selectinload(Evaluation.teacher),
        selectinload(Evaluation.grades),
    ]


def _eval_light_options() -> list[Any]:
    """Les seules relations que la liste affiche : matière, classe, enseignant."""
    return [
        selectinload(Evaluation.subject),
        selectinload(Evaluation.class_),
        selectinload(Evaluation.teacher),
    ]


def _filter_evaluations(
    stmt: Select[Any],
    *,
    class_id: int | None,
    teacher_id: int | None,
    academic_year_id: int | None,
    trimester: int | None,
) -> Select[Any]:
    if class_id is not None:
        stmt = stmt.where(Evaluation.class_id == class_id)
    if teacher_id is not None:
        stmt = stmt.where(Evaluation.teacher_id == teacher_id)
    if academic_year_id is not None:
        stmt = stmt.where(Evaluation.academic_year_id == academic_year_id)
    if trimester is not None:
        stmt = stmt.where(Evaluation.trimester == trimester)
    return stmt


async def get_evaluation_by_id(db: AsyncSession, eval_id: int) -> Evaluation | None:
    stmt = select(Evaluation).where(Evaluation.id == eval_id).options(*_eval_options())
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def list_evaluations(
    db: AsyncSession,
    *,
    class_id: int | None = None,
    teacher_id: int | None = None,
    academic_year_id: int | None = None,
    trimester: int | None = None,
) -> list[Evaluation]:
    """Toutes les évaluations correspondant aux filtres, notes comprises.

    Sans limite : appelée par le relevé de notes PDF et le récapitulatif de
    classe, qui ont besoin de la totalité d'un trimestre pour une classe. La
    liste exposée par l'API passe par `list_evaluations_page`.
    """
    stmt = select(Evaluation).options(*_eval_options()).order_by(Evaluation.date.desc())
    stmt = _filter_evaluations(
        stmt,
        class_id=class_id,
        teacher_id=teacher_id,
        academic_year_id=academic_year_id,
        trimester=trimester,
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def list_evaluations_page(
    db: AsyncSession,
    *,
    class_id: int | None = None,
    teacher_id: int | None = None,
    academic_year_id: int | None = None,
    trimester: int | None = None,
    page: int = 1,
    size: int = 20,
) -> tuple[list[Evaluation], int]:
    """Une page d'évaluations et le total de l'école pour ces filtres.

    Le total vient d'un COUNT sur la même clause WHERE : il ne dépend donc
    pas de la taille de la page. Les notes ne sont pas chargées, leurs
    compteurs étant obtenus par `count_grades_by_evaluation`.
    """
    base = _filter_evaluations(
        select(Evaluation),
        class_id=class_id,
        teacher_id=teacher_id,
        academic_year_id=academic_year_id,
        trimester=trimester,
    )

    count_stmt = select(func.count()).select_from(base.subquery())
    total: int = (await db.execute(count_stmt)).scalar() or 0

    stmt = (
        base.options(*_eval_light_options())
        # `id` départage les évaluations d'une même journée : sans lui, deux
        # pages successives peuvent réafficher ou sauter une ligne.
        .order_by(Evaluation.date.desc(), Evaluation.id.desc())
        .offset((page - 1) * size)
        .limit(size)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all()), total


async def count_grades_by_evaluation(
    db: AsyncSession, eval_ids: list[int]
) -> dict[int, EvaluationGradeCounts]:
    """Compte, par évaluation, ses élèves et ceux dont la note est saisie.

    Deux nombres par évaluation : les rapatrier ligne à ligne coûtait toutes
    les notes de l'école pour afficher « 12 / 35 ». Une évaluation dont
    aucune note n'existe est simplement absente du résultat ; l'appelant lit
    alors `NO_GRADES`.
    """
    if not eval_ids:
        return {}
    stmt = (
        select(
            Grade.evaluation_id,
            func.count().label("total"),
            func.sum(case((Grade.status == GradeStatus.ENTERED.value, 1), else_=0)).label("graded"),
        )
        .where(Grade.evaluation_id.in_(eval_ids))
        .group_by(Grade.evaluation_id)
    )
    rows = (await db.execute(stmt)).all()
    return {
        int(evaluation_id): EvaluationGradeCounts(total=int(total or 0), graded=int(graded or 0))
        for evaluation_id, total, graded in rows
    }


async def create_evaluation(
    db: AsyncSession,
    *,
    data: dict[str, Any],
    students: list[Student],
) -> Evaluation:
    """Crée l'évaluation et les Grade pending pour tous les élèves."""
    evaluation = Evaluation(**data)
    db.add(evaluation)
    await db.flush()  # obtenir l'ID

    for student in students:
        grade = Grade(
            evaluation_id=evaluation.id,
            student_id=student.id,
            status=GradeStatus.PENDING,
        )
        db.add(grade)

    await db.flush()
    await db.refresh(evaluation)
    return evaluation


# ---------------------------------------------------------------------------
# Grades
# ---------------------------------------------------------------------------


async def get_grades_for_evaluation(db: AsyncSession, eval_id: int) -> list[Grade]:
    stmt = (
        select(Grade)
        .where(Grade.evaluation_id == eval_id)
        .options(selectinload(Grade.student))
        .order_by(Grade.student_id)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def batch_update_grades(
    db: AsyncSession,
    eval_id: int,
    entries: list[dict[str, Any]],
    *,
    entered_by_user_id: int | None = None,
) -> list[Grade]:
    """Met à jour les notes en batch — entries = [{student_id, value}, ...].

    `entered_by_user_id` : audit trail pour la délégation (admin saisit
    pour un prof). NULL si non tracé.
    """
    for entry in entries:
        if entry.get("absent"):
            # Zéro d'office : la note existe et vaut 0, elle entre dans la
            # moyenne. C'est ce qu'un billet d'annulation de zéro pourra lever.
            values: dict[str, Any] = {
                "value": Decimal("0"),
                "status": GradeStatus.ABSENT,
            }
        elif entry["value"] is not None:
            values = {"value": entry["value"], "status": GradeStatus.ENTERED}
        else:
            # Case laissée vide : on repasse en « à saisir », SAUF si la note
            # portait un statut qui ne doit pas disparaître au premier
            # enregistrement de la feuille — un rattrapage autorisé et pas
            # encore noté se volatiliserait sinon, et l'élève retomberait à
            # zéro sans que personne ne l'ait décidé.
            values = {
                "value": None,
                "status": case(
                    (
                        Grade.status.in_([s.value for s in STICKY_GRADE_STATUSES]),
                        Grade.status,
                    ),
                    else_=GradeStatus.PENDING.value,
                ),
            }
        if entered_by_user_id is not None:
            values["entered_by_user_id"] = entered_by_user_id
        stmt = (
            update(Grade)
            .where(
                Grade.evaluation_id == eval_id,
                Grade.student_id == entry["student_id"],
            )
            .values(**values)
        )
        await db.execute(stmt)

    await db.flush()
    return await get_grades_for_evaluation(db, eval_id)


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


async def get_grades_summary(
    db: AsyncSession,
    class_id: int,
    trimester: int,
    academic_year_id: int,
) -> dict[str, Any]:
    """Calcule les moyennes pondérées par coefficient pour chaque élève."""
    # Toutes les évaluations du trimestre pour cette classe
    evals = await list_evaluations(
        db,
        class_id=class_id,
        academic_year_id=academic_year_id,
        trimester=trimester,
    )

    if not evals:
        return {"students": [], "subjects": []}

    eval_ids = [e.id for e in evals]

    # Toutes les notes
    stmt = (
        select(Grade)
        # Le zéro d'office compte dans la moyenne au même titre qu'une note
        # saisie : l'exclure reviendrait à récompenser l'absence.
        .where(
            Grade.evaluation_id.in_(eval_ids),
            Grade.status.in_([s.value for s in COUNTED_GRADE_STATUSES]),
            Grade.value.is_not(None),
        )
        .options(selectinload(Grade.student), selectinload(Grade.evaluation))
    )
    result = await db.execute(stmt)
    grades: list[Grade] = list(result.scalars().all())

    # Regrouper par (student_id, subject_id) pour moyennes par matière
    # Regrouper par student_id pour moyenne générale

    # Map evaluation → subject_id, coefficient
    eval_map = {e.id: e for e in evals}

    # subject averages : {subject_id: [(value, coeff)]}
    subject_grades: dict[int, list[tuple[Decimal, int]]] = {}
    # student averages: {student_id: [(value, combined_coeff)]}
    # combined_coeff = evaluation.coefficient × subject.coefficient
    student_grades: dict[int, list[tuple[Decimal, int]]] = {}
    student_summaries: list[dict[str, Any]] = []

    for g in grades:
        ev = eval_map[g.evaluation_id]
        if g.value is None:
            continue
        subject_coeff = ev.subject.coefficient if ev.subject else 1
        combined_coeff = ev.coefficient * subject_coeff
        # Subject (class average uses eval.coefficient only — same subject)
        subject_grades.setdefault(ev.subject_id, []).append((g.value, ev.coefficient))
        # Student (weighted by combined coefficient)
        student_grades.setdefault(g.student_id, []).append((g.value, combined_coeff))

    def weighted_avg(pairs: list[tuple[Decimal, int]]) -> Decimal | None:
        if not pairs:
            return None
        total_val = sum(v * c for v, c in pairs)
        total_coeff = sum(c for _, c in pairs)
        if total_coeff == 0:
            return None
        raw = Decimal(str(total_val / total_coeff))
        return raw.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # Récupérer tous les élèves de la classe
    students = await get_students_for_class(db, class_id, academic_year_id)
    student_map = {s.id: s for s in students}

    # Calculer moyennes et ranks
    for sid, s in student_map.items():
        avg = weighted_avg(student_grades.get(sid, []))
        student_summaries.append(
            {
                "student_id": sid,
                "student_name": _student_full_name(s),
                "average": avg,
                "mention": _compute_mention(avg),
            }
        )

    # Trier par moyenne décroissante pour les rangs
    student_summaries.sort(
        key=lambda x: x["average"] if x["average"] is not None else Decimal("0"),
        reverse=True,
    )
    # Competition ranking (1, 1, 3): les ex-aequo partagent le même rang
    rank = 1
    for i, item in enumerate(student_summaries):
        if item["average"] is None:
            item["rank"] = None
        else:
            if i > 0 and item["average"] == student_summaries[i - 1]["average"]:
                item["rank"] = student_summaries[i - 1]["rank"]
            else:
                item["rank"] = rank
            rank = i + 2  # prochain rang = position (1-indexed) + 1

    # Moyennes par matière
    subject_set = {eval_map[g.evaluation_id].subject_id for g in grades}
    subject_summaries: list[dict[str, Any]] = []
    for eval_ in evals:
        sid = eval_.subject_id
        if sid not in subject_set:
            continue
        avg = weighted_avg(subject_grades.get(sid, []))
        subject_summaries.append(
            {
                "subject_id": sid,
                "subject_name": eval_.subject.name if eval_.subject else "",
                "class_average": avg,
            }
        )
    # Dédupliquer
    seen: set[int] = set()
    unique_subjects: list[dict[str, Any]] = []
    for subj in subject_summaries:
        subj_id = int(subj["subject_id"])
        if subj_id not in seen:
            seen.add(subj_id)
            unique_subjects.append(subj)

    return {"students": student_summaries, "subjects": unique_subjects}


# ---------------------------------------------------------------------------
# Bulletin
# ---------------------------------------------------------------------------


async def upsert_bulletin(
    db: AsyncSession,
    *,
    student_id: int,
    class_id: int,
    academic_year_id: int,
    trimester: int,
    average: Decimal | None,
    rank: int | None,
    mention: str | None,
    file_url: str | None = None,
) -> Bulletin:
    """Crée ou met à jour le bulletin d'un élève."""
    stmt = select(Bulletin).where(
        Bulletin.student_id == student_id,
        Bulletin.class_id == class_id,
        Bulletin.academic_year_id == academic_year_id,
        Bulletin.trimester == trimester,
    )
    result = await db.execute(stmt)
    bulletin = result.scalar_one_or_none()

    if bulletin is None:
        bulletin = Bulletin(
            student_id=student_id,
            class_id=class_id,
            academic_year_id=academic_year_id,
            trimester=trimester,
            average=average,
            rank=rank,
            mention=mention,
            file_url=file_url,
        )
        db.add(bulletin)
    else:
        bulletin.average = average
        bulletin.rank = rank
        bulletin.mention = mention
        if file_url:
            bulletin.file_url = file_url

    await db.flush()
    return bulletin
