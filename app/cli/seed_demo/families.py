"""Les élèves, leurs familles et leurs inscriptions.

Un seul appel de service crée l'élève, son tuteur et l'inscription : c'est
celui que le secrétariat déclenche au guichet, et c'est lui qui pose aussi les
frais dus. Passer par lui plutôt que par trois insertions garantit que la
dette d'une famille de démonstration se calcule exactement comme celle d'une
famille réelle.

Les inscriptions ne sont pas toutes validées. Une école en fin d'année garde
des dossiers en cours d'instruction et des demandes jamais confirmées ; les
trois états existent donc, dans les proportions qu'on observe.
"""

from __future__ import annotations

import random
from datetime import date

from sqlalchemy import select

from app.cli.seed_demo import names, plan, portraits
from app.cli.seed_demo.context import DEMO_PASSWORD, FAMILY_DOMAIN, SeedContext, logger
from app.core.exceptions import BusinessValidationError
from app.models.enrollment import AssignmentStatus, Enrollment, EnrollmentStatus
from app.models.user import Parent, Student
from app.schemas.enrollment import EnrollmentUpdate, EnrollmentWithStudentCreate, ParentInput
from app.services import admin_service, enrollment_service

#: Répartition de l'affectation. Un privé ivoirien accueille une part
#: importante d'élèves affectés par l'État, c'est même son modèle
#: économique. Viennent ensuite quelques réaffectés d'un autre établissement, et des
#: non affectés qui paient le tarif plein.
_ASSIGNMENT_WEIGHTS: tuple[tuple[AssignmentStatus, int], ...] = (
    (AssignmentStatus.AFFECTE, 42),
    (AssignmentStatus.REAFFECTE, 8),
    (AssignmentStatus.NON_AFFECTE, 50),
)

#: États d'inscription. La grande majorité est validée : ce sont les élèves
#: qui ont effectivement fait l'année.
_STATUS_WEIGHTS: tuple[tuple[EnrollmentStatus, int], ...] = (
    (EnrollmentStatus.VALIDE, 90),
    (EnrollmentStatus.EN_VALIDATION, 6),
    (EnrollmentStatus.PROSPECT, 4),
)

#: Âge d'entrée en 6e, en Côte d'Ivoire comme ailleurs dans la sous-région.
_AGE_AT_SIXIEME = 11


def _weighted[T](rng: random.Random, weights: tuple[tuple[T, int], ...]) -> T:
    """Tire une valeur selon des poids entiers, de façon reproductible.

    Reproductible parce que le tirage vient du générateur graine du semis :
    relancer le script range le même élève dans la même catégorie, sinon la
    reprise créerait un second dossier pour la même famille.
    """
    total = sum(weight for _value, weight in weights)
    draw = rng.randint(1, total)
    running = 0
    for value, weight in weights:
        running += weight
        if draw <= running:
            return value
    return weights[-1][0]


def _birth_date(ctx: SeedContext, level_order: int) -> date:
    """Une date de naissance cohérente avec le niveau, redoublants compris."""
    year_start = int(ctx.academic_year_name.split("-")[0])
    expected = year_start - (_AGE_AT_SIXIEME + level_order - 1)
    # Un tiers des élèves a un an de retard : c'est la réalité des cohortes,
    # et c'est ce qui rend la pyramide des âges du rapport officiel crédible.
    shift = ctx.rng.choice((0, 0, 0, -1, -1, 1))
    return date(expected + shift, ctx.rng.randint(1, 12), ctx.rng.randint(1, 28))


async def _existing_matricules(ctx: SeedContext) -> dict[str, tuple[int, int]]:
    """Les élèves déjà semés, retrouvés par leur matricule.

    Le matricule est la clé de relance : il est unique en base, il ne dépend
    d'aucun tirage, et il permet de reprendre un semis interrompu sans créer
    une seconde fois les six cents élèves déjà en place.
    """
    stmt = (
        select(Student.enrollment_number, Student.id, Enrollment.id)
        .join(Enrollment, Enrollment.student_id == Student.id)
        .where(Enrollment.academic_year_id == ctx.academic_year_id)
    )
    return {
        str(matricule): (int(student_id), int(enrollment_id))
        for matricule, student_id, enrollment_id in (await ctx.db.execute(stmt)).all()
        if matricule
    }


def _parent_input(ctx: SeedContext, last_name: str, rank: int) -> ParentInput:
    """Le tuteur légal, avec ou sans compte selon le rang.

    Un quart des familles a un accès au portail : c'est l'ordre de grandeur
    réel, et c'est suffisant pour montrer le portail parent sans fabriquer six
    cents comptes que personne n'ouvrira.
    """
    genre = "M" if rank % 3 else "F"
    first_name, _ = names.pick_full_name(ctx.rng, genre)
    wants_account = rank % 4 == 0
    email = names.email_for(first_name, last_name, rank, FAMILY_DOMAIN)
    return ParentInput(
        first_name=first_name,
        last_name=last_name,
        phone=names.phone_number(ctx.rng),
        email=email,
        city="Abidjan",
        commune=ctx.rng.choice(names.COMMUNES),
        password=DEMO_PASSWORD if wants_account else None,
        relationship_type="father" if genre == "M" else "mother",
    )


async def _apply_status(ctx: SeedContext, enrollment_id: int, status: EnrollmentStatus) -> None:
    """Amène l'inscription à son état, par le chemin que suit le secrétariat."""
    if status is EnrollmentStatus.VALIDE:
        await enrollment_service.validate_enrollment(ctx.db, enrollment_id, ctx.actor_id)
    elif status is EnrollmentStatus.EN_VALIDATION:
        await enrollment_service.update_enrollment(
            ctx.db,
            enrollment_id,
            EnrollmentUpdate(status=EnrollmentStatus.EN_VALIDATION.value),
            ctx.actor_id,
        )


async def _decorate_student(
    ctx: SeedContext, student_id: int, matricule: str, first_name: str, last_name: str, rank: int
) -> None:
    """Portrait, provenance et commune : ce que les fiches et les PDF affichent."""
    student = await ctx.db.get(Student, student_id)
    if student is None:
        return
    if not student.photo_url:
        student.photo_url = portraits.portrait_url(matricule.lower(), first_name, last_name)
    if not student.city:
        student.city = "Abidjan"
        student.commune = ctx.rng.choice(names.COMMUNES)
    # Un élève sur huit vient d'un autre établissement : c'est lui dont le
    # secrétariat réclamera le dossier scolaire, et lui que le rapport
    # officiel compte dans ses mouvements d'effectifs.
    if rank % 8 == 0 and not student.previous_school:
        student.previous_school = ctx.rng.choice(names.PREVIOUS_SCHOOLS)
        student.transfer_decision_number = f"DECISION-{2025}-{rank:04d}"


async def enrol_cohorts(ctx: SeedContext) -> None:
    """Remplit chaque division, du collège au lycée."""
    already = await _existing_matricules(ctx)
    rank = 0

    for level, serie, division in plan.class_plan():
        class_id = ctx.class_ids[(level, serie, division)]
        level_order = next(order for name, order, _a in plan.LEVELS if name == level)
        size = plan.class_size(level, serie, division)

        for _seat in range(size):
            rank += 1
            matricule = ctx.matricule(rank)
            genre = "F" if rank % 2 == 0 else "M"
            first_name, last_name = names.pick_full_name(ctx.rng, genre)
            assignment = _weighted(ctx.rng, _ASSIGNMENT_WEIGHTS)
            status = _weighted(ctx.rng, _STATUS_WEIGHTS)
            parent = _parent_input(ctx, last_name, rank)
            birth = _birth_date(ctx, level_order)

            if matricule in already:
                ctx.students[matricule] = already[matricule]
                continue

            try:
                created = await enrollment_service.create_enrollment_with_student(
                    ctx.db,
                    EnrollmentWithStudentCreate(
                        first_name=first_name,
                        last_name=last_name,
                        birth_date=birth,
                        genre=genre,
                        enrollment_number=matricule,
                        city="Abidjan",
                        commune=parent.commune,
                        parent=parent,
                        class_id=class_id,
                        academic_year_id=ctx.academic_year_id,
                        assignment_status=assignment.value,
                        assignment_decision_number=(
                            f"AFF/{2025}/{rank:05d}" if assignment.is_subsidised else None
                        ),
                    ),
                    ctx.actor_id,
                )
            except BusinessValidationError as refus:
                # Une classe pleine ne doit pas arrêter le semis des dix-sept
                # autres. On le dit, on passe au siège suivant, et le compte
                # final montrera la division incomplète.
                logger.warning(
                    "%s %s : inscription refusée (%s)",
                    plan.class_display_name(level, division),
                    matricule,
                    refus.detail,
                )
                continue

            await _apply_status(ctx, created.id, status)
            await _decorate_student(ctx, created.student_id, matricule, first_name, last_name, rank)
            await ctx.db.commit()

            ctx.students[matricule] = (created.student_id, created.id)
            ctx.tally("élèves")
            ctx.tally("inscriptions")

    logger.info("Cohortes en place : %s élèves inscrits.", len(ctx.students))


async def link_siblings(ctx: SeedContext) -> None:
    """Rattache un second enfant à des tuteurs qui en ont déjà un.

    Une école compte des fratries, et la fiche parent n'a d'intérêt en
    démonstration que si elle en montre au moins quelques-unes : c'est là qu'on
    voit le solde consolidé du foyer.
    """
    parents = (await ctx.db.execute(select(Parent).order_by(Parent.id).limit(400))).scalars().all()
    matricules = sorted(ctx.students)
    if not parents or not matricules:
        return

    for offset, parent in enumerate(parents):
        if offset % 9:
            continue
        student_id, _enrollment_id = ctx.students[matricules[(offset * 7) % len(matricules)]]
        outcome = await admin_service.link_parent_to_student(
            ctx.db, parent.id, student_id, "guardian", linked_by=ctx.actor_id
        )
        if outcome:
            ctx.tally("fratries rattachées")


async def open_student_portals(ctx: SeedContext) -> None:
    """Donne un accès élève à une poignée d'inscrits.

    Peu, et volontairement : dans un collège ivoirien, c'est le parent qui a
    un téléphone et une adresse, pas l'élève de 6e. Une quinzaine de comptes
    suffit à montrer le portail élève.
    """
    for offset, matricule in enumerate(sorted(ctx.students)):
        if offset % 40 or offset > 600:
            continue
        student_id, _enrollment_id = ctx.students[matricule]
        student = await ctx.db.get(Student, student_id)
        if student is None or student.user_id:
            continue
        try:
            await admin_service.create_student_user_account(
                ctx.db,
                student_id,
                f"{matricule.lower()}@{FAMILY_DOMAIN}",
                DEMO_PASSWORD,
                created_by=ctx.actor_id,
            )
            ctx.tally("comptes élèves")
        except Exception:
            logger.exception("Compte élève non créé pour %s", matricule)


async def run(ctx: SeedContext) -> None:
    await enrol_cohorts(ctx)
    await link_siblings(ctx)
    await open_student_portals(ctx)
