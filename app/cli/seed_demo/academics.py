"""Une année académique entière : évaluations, notes, bulletins et conseils.

Deux idées portent ce module.

**Un élève a un niveau, et ce niveau le suit.** Chaque note est tirée autour
d'une aptitude propre à l'élève, dérivée de son seul identifiant, donc stable
d'une matière, d'un trimestre et d'une relance à l'autre. Des notes tirées
indépendamment donneraient à tout le monde la même moyenne, un classement sans
signification et des bulletins que personne ne peut commenter.

**On passe par les services, pas par les tables.** Ce sont eux qui préparent
la feuille de notes, calculent les moyennes par matière, classent la promotion
et fabriquent le procès-verbal. Un semis qui écrirait ses bulletins à la main
produirait des chiffres que l'application recalculerait autrement dès le
premier écran ouvert.

Une évaluation déjà semée n'est jamais renotée : réécrire une note existante
exige la permission `grades:edit`, et le service la refuse à juste titre. Le
semis ne saisit donc que les feuilles qu'il vient d'ouvrir.
"""

from __future__ import annotations

import random
from decimal import Decimal

from sqlalchemy import select

from app.cli.seed_demo import plan
from app.cli.seed_demo.context import SeedContext, logger
from app.cli.seed_demo.referentiel import SCHOOL_IDENTITY
from app.core.exceptions import BusinessValidationError
from app.models.academic import Subject
from app.models.enrollment import Enrollment, EnrollmentStatus
from app.models.grade import Bulletin, Evaluation, EvaluationType
from app.models.user import TeacherProfile
from app.schemas.council import (
    CouncilDecisionBatchItem,
    CouncilDecisionsBatchRequest,
    CouncilMinutesGenerateRequest,
)
from app.schemas.grades import EvaluationCreate, GradeBatchUpdate, GradeEntry
from app.services import council_service, grades_service, reports_service

#: Les deux épreuves de chaque matière et de chaque trimestre, telles que les
#: annonce le règlement intérieur : un devoir de contrôle, puis la composition
#: qui pèse double. Le dernier nombre est la place de l'épreuve dans le
#: calendrier du trimestre, pour que la composition tombe bien après le devoir.
_EPREUVES: tuple[tuple[str, EvaluationType, int, int], ...] = (
    ("Devoir n°1", EvaluationType.DEVOIR, 1, 2),
    ("Composition", EvaluationType.EXAMEN, 2, 6),
)

#: Nombre de jours de classe repérés dans un trimestre pour y placer les
#: épreuves. Huit suffisent à écarter le devoir de la composition.
_SCHOOL_DAYS = 8

_ORDINALS: dict[int, str] = {1: "1er", 2: "2e", 3: "3e"}
_TRIMESTERS: tuple[int, ...] = (1, 2, 3)

#: Paramètres du tirage des notes. La moyenne visée place les classes entre 9
#: et 13, l'écart laisse quelques excellents au-dessus de 16 et quelques élèves
#: réellement en difficulté sous 7.
_ABILITY_MEAN = 11.0
_ABILITY_SPREAD = 2.4
_SUBJECT_SPREAD = 1.2
_DAY_SPREAD = 1.3
#: Léger progrès d'un trimestre au suivant : une classe travaille.
_TRIMESTER_GAIN = 0.25
#: Part d'élèves absents le jour de l'épreuve. Ces zéros d'office doivent
#: exister : c'est sur eux que porte le billet d'annulation de zéro.
_ABSENCE_RATE = 0.03

#: Appréciations du professeur principal, par palier de moyenne.
_COMMENTS: tuple[tuple[float, str], ...] = (
    (16.0, "Excellent trimestre, continuez ainsi."),
    (14.0, "Très bon travail, le niveau se maintient."),
    (12.0, "Bon trimestre dans l'ensemble, poursuivez vos efforts."),
    (10.0, "Des résultats encourageants, il faut persévérer."),
    (8.5, "Résultats fragiles, un travail plus régulier est attendu."),
    (0.0, "Trimestre insuffisant, un sursaut est indispensable."),
)


def _ability(student_id: int) -> float:
    """Le niveau propre d'un élève, identique dans toutes les matières.

    Tiré de son seul identifiant, donc reproductible et surtout cohérent : le
    premier de la classe l'est aussi en physique, et c'est ce qui rend un
    bulletin et un classement lisibles.
    """
    return random.Random(student_id).gauss(_ABILITY_MEAN, _ABILITY_SPREAD)


def _subject_offset(student_id: int, subject_id: int) -> float:
    """Le goût de l'élève pour la matière : bon en français, faible en maths."""
    return random.Random(student_id * 10_007 + subject_id).gauss(0.0, _SUBJECT_SPREAD)


def _mark(ctx: SeedContext, student_id: int, subject_id: int, trimester: int) -> float:
    """La note du jour : le niveau de l'élève, plus la part de hasard d'une copie."""
    raw = (
        _ability(student_id)
        + _subject_offset(student_id, subject_id)
        + ctx.rng.gauss(0.0, _DAY_SPREAD)
        + _TRIMESTER_GAIN * (trimester - 1)
    )
    # Au quart de point : c'est le pas de correction réel d'une copie notée
    # sur 20, et le seul que les bulletins savent afficher proprement.
    return round(min(max(raw, 0.0), 20.0) * 4) / 4


def _comment_for(average: Decimal | None) -> str:
    """L'appréciation qui correspond à la moyenne du trimestre."""
    value = float(average) if average is not None else 0.0
    for floor, text in _COMMENTS:
        if value >= floor:
            return text
    return _COMMENTS[-1][1]


async def _students_by_class(ctx: SeedContext) -> dict[int, list[int]]:
    """Les élèves réellement inscrits dans chaque classe, en une requête.

    Même périmètre que le service qui prépare les feuilles de notes : les
    dossiers en cours d'instruction n'ont pas de note, donc pas de bulletin.
    """
    stmt = (
        select(Enrollment.class_id, Enrollment.student_id)
        .where(
            Enrollment.academic_year_id == ctx.academic_year_id,
            Enrollment.status == EnrollmentStatus.VALIDE.value,
        )
        .order_by(Enrollment.class_id, Enrollment.student_id)
    )
    rosters: dict[int, list[int]] = {}
    for class_id, student_id in (await ctx.db.execute(stmt)).all():
        rosters.setdefault(int(class_id), []).append(int(student_id))
    return rosters


async def _subject_teachers(ctx: SeedContext) -> dict[int, int]:
    """Le titulaire de chaque instance de matière, tel que l'école l'a désigné."""
    rows = (await ctx.db.execute(select(Subject.id, Subject.teacher_id))).all()
    return {int(subject_id): int(teacher_id) for subject_id, teacher_id in rows if teacher_id}


async def _teacher_names(ctx: SeedContext) -> dict[int, str]:
    """Le nom des enseignants, pour signer les procès-verbaux."""
    stmt = select(TeacherProfile.id, TeacherProfile.first_name, TeacherProfile.last_name)
    return {
        int(teacher_id): f"{first_name} {last_name}".strip()
        for teacher_id, first_name, last_name in (await ctx.db.execute(stmt)).all()
    }


async def _existing_evaluations(ctx: SeedContext) -> set[tuple[int, int, int, str]]:
    """Les épreuves déjà semées, retrouvées par (classe, matière, trimestre, titre).

    Chargées d'un coup : le semis en envisage plusieurs milliers, et une
    requête par épreuve envisagée coûterait plus cher que tout le reste.
    """
    stmt = select(
        Evaluation.class_id, Evaluation.subject_id, Evaluation.trimester, Evaluation.title
    ).where(Evaluation.academic_year_id == ctx.academic_year_id)
    return {
        (int(class_id), int(subject_id), int(trimester), str(title))
        for class_id, subject_id, trimester, title in (await ctx.db.execute(stmt)).all()
    }


async def _enter_marks(
    ctx: SeedContext, eval_id: int, roster: list[int], subject_id: int, trimester: int
) -> None:
    """Saisit la feuille de notes en une fois, absents compris."""
    entries = [
        GradeEntry(student_id=student_id, value=None, absent=True)
        if ctx.rng.random() < _ABSENCE_RATE
        else GradeEntry(student_id=student_id, value=_mark(ctx, student_id, subject_id, trimester))
        for student_id in roster
    ]
    await grades_service.batch_update_grades(
        ctx.db, eval_id, GradeBatchUpdate(grades=entries), ctx.actor_id
    )
    ctx.tally("notes", len(entries))


async def run_evaluations(ctx: SeedContext) -> None:
    """Ouvre et note deux épreuves par matière et par trimestre, dans chaque classe."""
    rosters = await _students_by_class(ctx)
    titulaires = await _subject_teachers(ctx)
    known = await _existing_evaluations(ctx)
    calendar = {trimester: ctx.school_days(trimester, _SCHOOL_DAYS) for trimester in _TRIMESTERS}

    for level, serie, division in plan.class_plan():
        class_id = ctx.class_ids[(level, serie, division)]
        roster = rosters.get(class_id, [])
        if not roster:
            logger.info("Classe %s sans inscrit validé : pas d'évaluation.", division)
            continue

        for name, _coefficient, _hours in plan.curriculum_for(level, serie):
            subject_id = ctx.subject_ids.get((level, serie, name))
            if subject_id is None:
                continue
            pool = ctx.teachers_by_subject.get(name) or []
            teacher_id = titulaires.get(subject_id) or (pool[0] if pool else None)
            if teacher_id is None:
                logger.info("Matière « %s » sans enseignant : épreuves sautées.", name)
                continue

            for trimester in _TRIMESTERS:
                days = calendar[trimester]
                if not days:
                    continue
                for label, kind, coefficient, slot in _EPREUVES:
                    title = f"{label} — {_ORDINALS[trimester]} trimestre"
                    if (class_id, subject_id, trimester, title) in known:
                        continue
                    created = await grades_service.create_evaluation(
                        ctx.db,
                        EvaluationCreate(
                            title=title,
                            type=kind,
                            date=days[min(slot, len(days) - 1)],
                            coefficient=coefficient,
                            subject_id=subject_id,
                            class_id=class_id,
                            academic_year_id=ctx.academic_year_id,
                            trimester=trimester,
                            teacher_id=teacher_id,
                        ),
                        teacher_id,
                        ctx.actor_id,
                    )
                    known.add((class_id, subject_id, trimester, title))
                    ctx.tally("évaluations")
                    await _enter_marks(ctx, int(created["id"]), roster, subject_id, trimester)


def _main_teacher(
    ctx: SeedContext,
    level: str,
    serie: str | None,
    titulaires: dict[int, int],
    names: dict[int, str],
) -> str | None:
    """Le professeur principal : le titulaire de la première matière du programme.

    Le programme est ordonné par poids, donc c'est le professeur de français ou
    de mathématiques qui signe le procès-verbal. C'est la règle de la maison.
    """
    for name, _coefficient, _hours in plan.curriculum_for(level, serie):
        subject_id = ctx.subject_ids.get((level, serie, name))
        teacher_id = titulaires.get(subject_id) if subject_id else None
        if teacher_id and teacher_id in names:
            return names[teacher_id]
    return None


async def _comment_bulletins(ctx: SeedContext, class_id: int, trimester: int) -> None:
    """Pose l'appréciation du professeur principal là où elle manque.

    Là où elle manque seulement : une appréciation rédigée par l'école vaut
    mieux que la nôtre, et un bulletin déjà remis ne se réécrit pas.
    """
    stmt = select(Bulletin).where(
        Bulletin.class_id == class_id,
        Bulletin.trimester == trimester,
        Bulletin.academic_year_id == ctx.academic_year_id,
        Bulletin.teacher_comment.is_(None),
    )
    for bulletin in (await ctx.db.execute(stmt)).scalars().all():
        bulletin.teacher_comment = _comment_for(bulletin.average)
        ctx.tally("appréciations")
    await ctx.db.commit()


async def _hold_council(
    ctx: SeedContext, class_id: int, trimester: int, main_teacher: str | None
) -> None:
    """Tient le conseil de classe, arrête ses décisions et publie le procès-verbal.

    Le conseil entérine la proposition automatique : c'est le cas ordinaire, et
    un PV sans décision finale ne se signe pas. Le service régénère le PV à
    chaque appel, ce qui rend cette étape rejouable telle quelle.
    """
    try:
        council = await council_service.generate_council_minutes(
            ctx.db,
            CouncilMinutesGenerateRequest(
                class_id=class_id,
                trimester=trimester,
                academic_year_id=ctx.academic_year_id,
                main_teacher_name=main_teacher,
                director_name=SCHOOL_IDENTITY["head_master_name"],
                dren_name=SCHOOL_IDENTITY["drena_name"],
                notes=None,
            ),
            ctx.actor_id,
        )
    except BusinessValidationError as error:
        logger.info("Conseil non tenu (classe %s, T%s) : %s", class_id, trimester, error)
        return

    decisions = [
        CouncilDecisionBatchItem(
            student_id=decision.student_id,
            final_decision=decision.auto_decision,
            override_reason=None,
        )
        for decision in council.decisions
    ]
    if decisions:
        await council_service.update_decisions_batch(
            ctx.db,
            council.id,
            CouncilDecisionsBatchRequest(decisions=decisions),
            ctx.actor_id,
        )
    await council_service.validate_council_minutes(ctx.db, council.id, ctx.actor_id)
    ctx.tally("conseils de classe")


async def publish_bulletins_and_councils(ctx: SeedContext) -> None:
    """Édite, publie et délibère les trois trimestres de chaque classe."""
    titulaires = await _subject_teachers(ctx)
    names = await _teacher_names(ctx)

    for level, serie, division in plan.class_plan():
        class_id = ctx.class_ids[(level, serie, division)]
        main_teacher = _main_teacher(ctx, level, serie, titulaires, names)
        label = plan.class_display_name(level, division)

        for trimester in _TRIMESTERS:
            try:
                report = await reports_service.generate_bulletins(
                    ctx.db,
                    class_id=class_id,
                    trimester=trimester,
                    academic_year_id=ctx.academic_year_id,
                    generated_by=ctx.actor_id,
                )
            except BusinessValidationError as error:
                logger.info("Bulletins non générés (%s, T%s) : %s", label, trimester, error)
                continue

            ctx.tally("bulletins", report.generated)
            await _comment_bulletins(ctx, class_id, trimester)
            published = await reports_service.publish_bulletins(
                ctx.db, class_id, trimester, ctx.academic_year_id, published_by=ctx.actor_id
            )
            ctx.tally("bulletins publiés", published)
            await _hold_council(ctx, class_id, trimester, main_teacher)


async def run(ctx: SeedContext) -> None:
    await run_evaluations(ctx)
    await publish_bulletins_and_councils(ctx)
