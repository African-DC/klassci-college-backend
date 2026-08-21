"""Les quatre tableaux du rapport DEEP que rien n'alimente encore.

Le canevas de fin de trimestre de la DEEP compte vingt-sept tableaux. Quatre
d'entre eux portent sur des faits que le logiciel enregistre bien, mais qu'aucun
écran ne permet encore de saisir : les visites de classe, les formations
d'enseignants, les transferts et réintégrations, et les bourses. Sur une base
vierge, ces tableaux s'impriment avec la mention « À compléter manuellement »,
ce qui est exactement ce qu'un établissement cherche à éviter en s'équipant.

L'écriture passe donc directement par les modèles. Ce n'est pas un raccourci
pris par confort : il n'existe ni service ni route pour ces quatre tables, et le
seul chemin possible est celui-ci tant que les écrans de saisie n'existent pas.

Deux d'entre elles ne remontent au rapport que si l'inscription rattachée
appartient à l'année visée et n'est ni rejetée ni annulée. Les inscriptions sont
donc lues en base, jamais devinées : une bourse accrochée à un dossier abandonné
gonflerait le tableau des boursiers sans qu'aucun élève ne soit boursier.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.cli.seed_demo.context import SeedContext, logger
from app.models.deep_report import (
    ClassVisit,
    Scholarship,
    ScholarshipKind,
    StudentTransfer,
    TeacherTraining,
    TransferKind,
)
from app.models.enrollment import Enrollment, EnrollmentStatus
from app.models.user import Student

VISIT_COUNT = 25
TRAINING_COUNT = 18
TRANSFER_COUNT = 20
SCHOLARSHIP_COUNT = 30

#: Qui visite les classes dans un privé ivoirien. L'inspecteur de la DRENA passe
#: une à deux fois l'an ; le reste des visites est interne.
_VISITORS: tuple[str, ...] = (
    "M. l'Inspecteur Pédagogique Régional",
    "Le Directeur des études",
    "Le Directeur général",
    "Mme la Censeure",
    "Le Conseiller pédagogique DRENA",
)

_VISIT_OBSERVATIONS: tuple[str, ...] = (
    "Progression conforme au programme officiel, cahier de textes à jour.",
    "Bonne maîtrise de la classe, participation des élèves à encourager.",
    "Fiche de préparation à détailler, objectifs de séance à formuler.",
    "Évaluations trop espacées, prévoir un devoir supplémentaire par trimestre.",
    "Séance bien conduite, gestion du temps à resserrer sur la phase de synthèse.",
)

#: Formations continues réellement proposées aux enseignants du secondaire en
#: Côte d'Ivoire, entre séminaires DRENA et ateliers d'établissement.
_TRAININGS: tuple[tuple[str, str], ...] = (
    ("Séminaire APC : approche par les compétences", "Transversal"),
    ("Atelier de remédiation en lecture", "Français"),
    ("Formation à l'évaluation par compétences", "Transversal"),
    ("Recyclage disciplinaire DRENA", "Disciplinaire"),
    ("Atelier numérique éducatif et usage du tableau", "Transversal"),
    ("Séminaire de préparation aux examens du BEPC", "Disciplinaire"),
)

_TRANSFER_OBSERVATIONS: tuple[str, ...] = (
    "Dossier scolaire reçu de l'établissement d'origine.",
    "Décision d'affectation présentée au secrétariat.",
    "Réintégration après une année d'interruption.",
)

#: Organismes qui financent réellement une scolarité privée : l'État pour les
#: élèves affectés méritants, les fondations d'entreprise, et le COGES pour les
#: familles en difficulté signalées par l'assistante sociale.
_PROVIDERS: tuple[str, ...] = (
    "État de Côte d'Ivoire",
    "Fondation Sifca",
    "COGES du collège",
    "Fondation Orange Côte d'Ivoire",
)

#: Montants notifiés, en francs ronds : une bourse entière couvre la scolarité
#: d'un cycle, la demi-bourse la moitié.
_AMOUNTS: dict[str, tuple[Decimal, ...]] = {
    ScholarshipKind.BOURSE_ENTIERE.value: (
        Decimal("120000"),
        Decimal("100000"),
        Decimal("90000"),
    ),
    ScholarshipKind.DEMI_BOURSE.value: (
        Decimal("60000"),
        Decimal("50000"),
        Decimal("45000"),
    ),
}


def _spread_days(ctx: SeedContext, count: int) -> list[date]:
    """Des jours de classe répartis sur les trois trimestres de l'année.

    Une inspection ne passe pas trois fois la même semaine puis plus jamais :
    étaler les dates est ce qui rend le tableau des visites lisible.
    """
    per_trimester = max(1, count // max(1, len(ctx.trimesters)) + 1)
    days: list[date] = []
    for order, _start, _end in ctx.trimesters:
        days.extend(ctx.school_days(order, per_trimester))
    return sorted(days)[:count]


def _teacher_roster(ctx: SeedContext) -> list[tuple[int, str]]:
    """Les enseignants du semis, chacun avec sa matière, dans un ordre stable."""
    roster: list[tuple[int, str]] = []
    for subject_name in sorted(ctx.teachers_by_subject):
        for teacher_id in ctx.teachers_by_subject[subject_name]:
            roster.append((teacher_id, subject_name))
    return roster


def _subject_instances(ctx: SeedContext) -> dict[str, int]:
    """Une instance de matière par nom, pour rattacher visite et formation.

    Le rapport agrège par discipline : n'importe quelle instance du référentiel
    porte le bon nom, et la classe visitée dit déjà le niveau concerné.
    """
    instances: dict[str, int] = {}
    for (_level, _serie, name), subject_id in ctx.subject_ids.items():
        instances.setdefault(name, subject_id)
    return instances


async def ensure_class_visits(ctx: SeedContext) -> None:
    """Les visites de classe de l'année, une ligne par passage."""
    roster = _teacher_roster(ctx)
    days = _spread_days(ctx, VISIT_COUNT)
    classes = sorted(ctx.class_ids.values())
    if not roster or not days or not classes:
        logger.info("Équipe ou calendrier incomplets : tableau des visites laissé vide.")
        return

    instances = _subject_instances(ctx)
    existing = {
        (row.teacher_id, row.visit_date, row.academic_year_id)
        for row in (
            await ctx.db.execute(
                select(ClassVisit).where(ClassVisit.academic_year_id == ctx.academic_year_id)
            )
        )
        .scalars()
        .all()
    }

    for index in range(VISIT_COUNT):
        teacher_id, subject_name = roster[index % len(roster)]
        visit_date = days[index % len(days)]
        if (teacher_id, visit_date, ctx.academic_year_id) in existing:
            continue
        ctx.db.add(
            ClassVisit(
                teacher_id=teacher_id,
                subject_id=instances.get(subject_name),
                class_id=classes[index % len(classes)],
                academic_year_id=ctx.academic_year_id,
                visit_date=visit_date,
                visitor_name=_VISITORS[index % len(_VISITORS)],
                observations=_VISIT_OBSERVATIONS[index % len(_VISIT_OBSERVATIONS)],
            )
        )
        ctx.tally("visites de classe")

    await ctx.db.commit()


async def ensure_trainings(ctx: SeedContext) -> None:
    """Les formations suivies par l'équipe, une ligne par enseignant formé."""
    roster = _teacher_roster(ctx)
    days = _spread_days(ctx, TRAINING_COUNT)
    if not roster or not days:
        logger.info("Équipe ou calendrier incomplets : tableau des formations laissé vide.")
        return

    instances = _subject_instances(ctx)
    existing = {
        (row.teacher_id, row.title, row.training_date)
        for row in (
            await ctx.db.execute(
                select(TeacherTraining).where(
                    TeacherTraining.academic_year_id == ctx.academic_year_id
                )
            )
        )
        .scalars()
        .all()
    }

    for index in range(TRAINING_COUNT):
        teacher_id, subject_name = roster[index % len(roster)]
        title, discipline = _TRAININGS[index % len(_TRAININGS)]
        training_date = days[index % len(days)]
        if (teacher_id, title, training_date) in existing:
            continue
        # Une formation transversale ne se rattache à aucune matière : le champ
        # en clair porte alors la discipline, comme le prévoit le modèle.
        disciplinary = discipline == "Disciplinaire"
        ctx.db.add(
            TeacherTraining(
                teacher_id=teacher_id,
                subject_id=instances.get(subject_name) if disciplinary else None,
                academic_year_id=ctx.academic_year_id,
                discipline_label=subject_name if disciplinary else discipline,
                title=title,
                training_date=training_date,
                observations="Attestation de participation remise à l'établissement.",
            )
        )
        ctx.tally("formations d'enseignants")

    await ctx.db.commit()


async def _reportable_enrollments(ctx: SeedContext) -> list[Enrollment]:
    """Les inscriptions que le rapport accepte de compter, élève compris.

    Le canevas décrit l'année en cours : un dossier rejeté ou annulé n'y a pas
    sa place, et une bourse posée dessus ne serait jamais imprimée.
    """
    stmt = (
        select(Enrollment)
        .where(
            Enrollment.academic_year_id == ctx.academic_year_id,
            Enrollment.status.in_([EnrollmentStatus.VALIDE, EnrollmentStatus.EN_VALIDATION]),
        )
        .options(selectinload(Enrollment.student))
        .order_by(Enrollment.id)
    )
    return list((await ctx.db.execute(stmt)).scalars().all())


async def ensure_transfers(ctx: SeedContext) -> None:
    """Les arrivées de l'année : transferts d'un autre collège, réintégrations."""
    enrollments = await _reportable_enrollments(ctx)
    if not enrollments:
        logger.info("Aucune inscription retenue : tableau des transferts laissé vide.")
        return

    existing = set((await ctx.db.execute(select(StudentTransfer.enrollment_id))).scalars().all())
    # Le chiffre visé est un total, jamais un lot supplémentaire. Sans cette
    # borne, chaque relance ajoutait vingt lignes de plus au tableau des
    # mouvements, et le rapport officiel finissait par déclarer plus d'arrivées
    # que l'école ne compte d'élèves.
    quota = TRANSFER_COUNT - len(existing)
    if quota <= 0:
        return
    # Les élèves venus d'ailleurs d'abord : leur établissement d'origine est déjà
    # sur leur fiche, et le tableau doit le reprendre tel quel.
    ordered = sorted(
        enrollments,
        key=lambda row: (row.student is None or not row.student.previous_school, row.id),
    )

    written = 0
    for index, enrollment in enumerate(ordered):
        if written >= quota:
            break
        if enrollment.id in existing:
            continue
        student: Student | None = enrollment.student
        kind = TransferKind.TRANSFERT if index % 5 else TransferKind.REINTEGRATION
        decision = (student.transfer_decision_number if student else None) or (
            f"DEC-{ctx.academic_year_name[:4]}/{enrollment.id:04d}"
        )
        ctx.db.add(
            StudentTransfer(
                enrollment_id=enrollment.id,
                kind=kind,
                origin_school=(student.previous_school if student else None)
                or "Établissement non précisé par la famille",
                decision_number=decision,
                transfer_date=ctx.trimesters[0][1] if ctx.trimesters else ctx.today,
                observations=_TRANSFER_OBSERVATIONS[index % len(_TRANSFER_OBSERVATIONS)],
            )
        )
        written += 1
        ctx.tally("transferts et réintégrations")

    await ctx.db.commit()


async def ensure_scholarships(ctx: SeedContext) -> None:
    """Les bourses et demi-bourses notifiées à l'établissement."""
    enrollments = await _reportable_enrollments(ctx)
    if not enrollments:
        logger.info("Aucune inscription retenue : tableau des bourses laissé vide.")
        return

    existing = set((await ctx.db.execute(select(Scholarship.enrollment_id))).scalars().all())
    # Même règle que pour les transferts : un total, pas un lot par exécution.
    quota = SCHOLARSHIP_COUNT - len(existing)
    if quota <= 0:
        return
    granted_on = ctx.trimesters[0][1] if ctx.trimesters else ctx.today

    written = 0
    for index, enrollment in enumerate(enrollments):
        if written >= quota:
            break
        if enrollment.id in existing:
            continue
        # Une bourse entière sur trois : les demi-bourses sont la règle, et un
        # tableau où tout le monde est boursier entier ne serait pas crédible.
        kind = ScholarshipKind.BOURSE_ENTIERE if index % 3 == 0 else ScholarshipKind.DEMI_BOURSE
        amounts = _AMOUNTS[kind.value]
        ctx.db.add(
            Scholarship(
                enrollment_id=enrollment.id,
                kind=kind,
                provider=_PROVIDERS[index % len(_PROVIDERS)],
                decision_number=f"BRS-{ctx.academic_year_name[:4]}/{enrollment.id:04d}",
                amount=amounts[index % len(amounts)],
                granted_on=granted_on,
                observations="Notification reçue par le secrétariat, pièce classée au dossier.",
            )
        )
        written += 1
        ctx.tally("bourses")

    await ctx.db.commit()


async def run(ctx: SeedContext) -> None:
    await ensure_class_visits(ctx)
    await ensure_trainings(ctx)
    await ensure_transfers(ctx)
    await ensure_scholarships(ctx)
