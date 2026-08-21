"""Les registres de l'éducateur : convocations, rattrapages, billets, dossiers.

Ces quatre registres sont ceux qu'un surveillant général tient à la main dans
un cahier, et qu'une démonstration doit montrer remplis. Un registre vide ne
prouve rien ; un registre dont toutes les lignes sont closes n'en prouve guère
plus, parce qu'une convocation attend souvent sa réponse plusieurs semaines.
Les proportions retenues sont celles d'une année ordinaire : environ sept
convocations sur dix ont reçu leur suite, les autres restent ouvertes.

**Deux gardes du logiciel se contredisent sur les dates.** Une convocation ne
s'émet pas pour hier (on ne couvre pas après coup une réunion déjà tenue) et
une suite ne se note pas avant le jour du rendez-vous. Un registre d'année
entière ne peut donc pas se poser en un seul appel : le semis émet à la date du
jour, replace ensuite la ligne à sa date réelle, puis note la suite. Les deux
gardes protègent le guichet, pas la reconstitution d'un historique.
"""

from __future__ import annotations

from datetime import date, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.cli.seed_demo.context import SeedContext, logger
from app.models.attendance import AttendanceContext, AttendanceRecord, AttendanceStatus
from app.models.document_issuance import DocumentIssuance
from app.models.enrollment import Enrollment, EnrollmentStatus
from app.models.grade import Evaluation, Grade, GradeStatus
from app.models.school_life import ParentSummons, RetakeAuthorization, SummonsOutcome
from app.models.user import ParentStudent, Student
from app.schemas.school_life import (
    ParentSummonsCreate,
    RetakeAuthorizationCreate,
    SummonsOutcomeUpdate,
)
from app.services.school_life import (
    entry_slip_service,
    retake_service,
    school_file_request_service,
    summons_service,
)

#: Justification que le tuteur fait porter au dos du billet.
_SLIP_NOTE = "Justificatif présenté par le tuteur au bureau de la vie scolaire"

#: Début de la mention que le service écrit sur l'appel régularisé. C'est par
#: elle qu'une relance reconnaît les billets déjà émis : régulariser une
#: absence la fait sortir du registre des absences, il ne reste donc rien
#: d'autre à quoi se raccrocher.
_SLIP_MARK = "Régularisée par billet d'entrée"

SUMMONS_COUNT = 40
RETAKE_COUNT = 12
ENTRY_SLIP_COUNT = 15
FILE_REQUEST_COUNT = 8

#: Motifs réellement dictés au guichet d'un collège ivoirien, dans l'ordre de
#: leur fréquence : l'assiduité passe avant les résultats, qui passent avant la
#: discipline.
_REASONS: tuple[str, ...] = (
    "Absences répétées en cours de mathématiques",
    "Résultats en baisse au 2e trimestre",
    "Comportement en classe",
    "Retards répétés à la première heure",
    "Frais de scolarité en souffrance",
    "Travail personnel insuffisant signalé par le conseil",
)

_ATTENDED_NOTES: tuple[str, ...] = (
    "Tuteur reçu par l'éducateur, engagement écrit sur l'assiduité.",
    "Entretien tenu en présence du professeur principal.",
    "Le tuteur s'engage à régulariser avant la fin du mois.",
)

_MISSED_NOTES: tuple[str, ...] = (
    "Tuteur non présenté, convocation à renouveler.",
    "Absent au rendez-vous, prévenu par téléphone le jour même.",
)

_RETAKE_REASONS: tuple[str, ...] = (
    "Hospitalisation justifiée par certificat médical",
    "Deuil familial attesté par le tuteur",
    "Absence justifiée par le tuteur auprès de l'éducateur",
)


def _educator_id(ctx: SeedContext) -> int:
    """L'éducateur signe ces actes, pas le compte technique du semis.

    Le registre affiche l'agent émetteur : y lire l'administrateur du script au
    lieu du surveillant général enlèverait à l'écran sa vraisemblance.
    """
    return ctx.staff_user_by_role.get("educator") or ctx.actor_id


async def _enrolled_students(ctx: SeedContext) -> list[int]:
    """Les élèves dont l'inscription de l'année est validée, dans un ordre stable.

    Un acte de vie scolaire exige cette inscription : le service refuse d'agir
    sur un dossier encore en instruction, et il a raison de le faire.
    """
    stmt = select(Enrollment.student_id).where(
        Enrollment.academic_year_id == ctx.academic_year_id,
        Enrollment.status == EnrollmentStatus.VALIDE,
    )
    return list((await ctx.db.execute(stmt.order_by(Enrollment.id))).scalars().all())


async def _students_at_risk(ctx: SeedContext, pool: list[int]) -> list[int]:
    """Les élèves qu'on convoque vraiment : ceux dont le cahier d'appel parle.

    Convoquer au hasard produirait un registre que le conseil de classe ne
    saurait pas relire : le tuteur d'un élève sans une absence ni un retard n'a
    aucune raison d'être appelé au collège.
    """
    stmt = select(AttendanceRecord.student_id).where(
        AttendanceRecord.status.in_([AttendanceStatus.ABSENT, AttendanceStatus.LATE])
    )
    flagged = set((await ctx.db.execute(stmt.distinct())).scalars().all())
    at_risk = [student_id for student_id in pool if student_id in flagged]
    return at_risk or pool


async def _families(ctx: SeedContext, ids: list[int]) -> tuple[dict[int, int], dict[int, str]]:
    """Le tuteur fiché de chaque élève, et son nom de famille à défaut.

    Beaucoup de familles n'ont pas encore de fiche parent : la convocation doit
    alors sortir au nom dicté au guichet, jamais au nom de personne.
    """
    if not ids:
        return {}, {}
    links: dict[int, int] = {}
    rows = await ctx.db.execute(select(ParentStudent).where(ParentStudent.student_id.in_(ids)))
    for link in rows.scalars().all():
        links.setdefault(link.student_id, link.parent_id)
    named = await ctx.db.execute(select(Student.id, Student.last_name).where(Student.id.in_(ids)))
    return links, {row[0]: row[1] for row in named.all()}


async def _emit_summons(
    ctx: SeedContext,
    *,
    student_id: int,
    parent_id: int | None,
    parent_name: str,
    day: date,
    reason: str,
    actor: int,
) -> ParentSummons | None:
    """Émet la convocation, puis la replace à sa date réelle dans l'année."""
    try:
        response = await summons_service.create_summons(
            ctx.db,
            ParentSummonsCreate(
                student_id=student_id,
                parent_id=parent_id,
                parent_name=None if parent_id else parent_name,
                summons_date=max(day, date.today()),
                summons_time=time(8 + day.toordinal() % 4, 0 if day.day % 2 else 30),
                reason=reason,
                trimester=ctx.trimester_of(day),
            ),
            actor_id=actor,
        )
    except Exception as error:  # noqa: BLE001 : une convocation refusée n'arrête rien
        await ctx.db.rollback()
        logger.warning("Convocation non émise pour l'élève %s : %s", student_id, error)
        return None

    summons = await ctx.db.get(ParentSummons, response.id)
    if summons is not None and summons.summons_date != day:
        summons.summons_date = day
        await ctx.db.commit()
    ctx.tally("convocations de tuteur")
    return summons


async def _record_outcome(ctx: SeedContext, summons_id: int, *, index: int, actor: int) -> None:
    """Note si le tuteur s'est présenté : trois fois sur quatre, il vient."""
    attended = index % 4 != 3
    wording = _ATTENDED_NOTES if attended else _MISSED_NOTES
    outcome = SummonsOutcome.ATTENDED if attended else SummonsOutcome.MISSED
    try:
        await summons_service.record_outcome(
            ctx.db,
            summons_id,
            SummonsOutcomeUpdate(outcome=outcome.value, notes=wording[index % len(wording)]),
            actor_id=actor,
        )
    except Exception as error:  # noqa: BLE001
        await ctx.db.rollback()
        logger.warning("Suite non enregistrée sur la convocation %s : %s", summons_id, error)
        return
    ctx.tally("suites de convocation")


async def ensure_summons(ctx: SeedContext) -> None:
    """Le registre des convocations d'une année, suites comprises."""
    enrolled = await _enrolled_students(ctx)
    if not enrolled:
        logger.info("Aucune inscription validée : registre des convocations laissé vide.")
        return

    pool = (await _students_at_risk(ctx, enrolled))[:SUMMONS_COUNT]
    guardians, names = await _families(ctx, pool)
    actor = _educator_id(ctx)
    today = date.today()

    rows = (await ctx.db.execute(select(ParentSummons))).scalars().all()
    existing = {(row.student_id, row.summons_date, row.reason): row for row in rows}
    # Le quota est un total. Le classement des élèves « à surveiller » bouge
    # d'une exécution à l'autre, puisque régulariser une absence la retire du
    # décompte : sans cette borne, chaque relance convoquerait quarante
    # nouvelles familles au lieu de retrouver les siennes.
    missing = max(0, SUMMONS_COUNT - len(rows))
    calendar = {order: ctx.school_days(order, 14) for order, _start, _end in ctx.trimesters}

    for index, student_id in enumerate(pool):
        days = calendar.get(index % 3 + 1) or []
        if not days:
            continue
        day = days[(index // 3) % len(days)]
        reason = _REASONS[index % len(_REASONS)]

        summons = existing.get((student_id, day, reason))
        if summons is None and missing > 0:
            missing -= 1
            summons = await _emit_summons(
                ctx,
                student_id=student_id,
                parent_id=guardians.get(student_id),
                parent_name=f"M. {names.get(student_id, 'le tuteur')}",
                day=day,
                reason=reason,
                actor=actor,
            )
        if summons is None:
            continue

        # Sept lignes sur dix ont reçu leur suite ; les autres restent en
        # attente, comme dans un cahier tenu en cours d'année.
        pending = summons.outcome == SummonsOutcome.PENDING
        if index % 10 < 7 and pending and summons.summons_date <= today:
            await _record_outcome(ctx, summons.id, index=index, actor=actor)


async def ensure_retakes(ctx: SeedContext) -> None:
    """Des billets d'annulation de zéro sur des épreuves réellement manquées.

    Le service refuse tout ce qui n'est pas un zéro d'office : on part donc des
    notes portées « absent » plutôt que d'inventer des évaluations. Le semis est
    idempotent par construction, la note visée cessant d'être « absent » dès que
    le billet est établi.
    """
    year = ctx.academic_year_id
    stmt = (
        select(Grade)
        .join(Evaluation, Grade.evaluation_id == Evaluation.id)
        .where(Grade.status == GradeStatus.ABSENT, Evaluation.academic_year_id == year)
        .options(selectinload(Grade.evaluation))
        .order_by(Grade.student_id, Evaluation.trimester, Grade.id)
    )
    enrolled = set(await _enrolled_students(ctx))
    buckets: dict[tuple[int, int], list[Grade]] = {}
    for grade in (await ctx.db.execute(stmt)).scalars().all():
        if grade.student_id not in enrolled or grade.evaluation is None:
            continue
        buckets.setdefault((grade.student_id, grade.evaluation.trimester), []).append(grade)

    actor = _educator_id(ctx)
    # Un billet consomme le zéro d'office qu'il vise : à la relance suivante,
    # les notes déjà couvertes ne sont plus « absent » et le semis en
    # choisirait douze autres. On compte donc les billets déjà établis.
    issued = int(
        (await ctx.db.execute(select(func.count()).select_from(RetakeAuthorization))).scalar_one()
    )
    for (student_id, _trimester), grades in buckets.items():
        if issued >= RETAKE_COUNT:
            break
        # Deux épreuves au plus : un billet couvre une absence, pas un trimestre.
        targets = grades[:2]
        days = sorted(grade.evaluation.date for grade in targets if grade.evaluation)
        try:
            await retake_service.create_authorization(
                ctx.db,
                RetakeAuthorizationCreate(
                    student_id=student_id,
                    period_start=days[0],
                    period_end=days[-1],
                    reason=_RETAKE_REASONS[issued % len(_RETAKE_REASONS)],
                    evaluation_ids=[grade.evaluation_id for grade in targets],
                ),
                actor_id=actor,
            )
        except Exception as error:  # noqa: BLE001
            await ctx.db.rollback()
            logger.warning("Billet de rattrapage refusé pour l'élève %s : %s", student_id, error)
            continue
        issued += 1
        ctx.tally("billets d'annulation de zéro")


async def ensure_entry_slips(ctx: SeedContext) -> None:
    """Des absences fermées par un billet d'entrée, comme au portail le matin.

    Le billet bascule l'appel en « excusé » : régulariser deux fois la même
    absence est impossible, le passage suivant ne la retrouve plus parmi les
    absences ouvertes.
    """
    today = ctx.today
    stmt = (
        select(AttendanceRecord)
        .join(AttendanceContext, AttendanceRecord.context_id == AttendanceContext.id)
        .where(AttendanceRecord.status == AttendanceStatus.ABSENT, AttendanceContext.date <= today)
        .options(selectinload(AttendanceRecord.context))
        .order_by(AttendanceRecord.id)
    )
    enrolled = set(await _enrolled_students(ctx))
    actor = _educator_id(ctx)
    # Régulariser une absence la fait sortir du registre des absences : on
    # compte donc les billets déjà émis à leur trace, la justification portée
    # sur l'appel, pour ne pas en produire quinze de plus à chaque relance.
    closed = int(
        (
            await ctx.db.execute(
                select(func.count())
                .select_from(AttendanceRecord)
                .where(AttendanceRecord.notes.like(f"{_SLIP_MARK}%"))
            )
        ).scalar_one()
    )

    for record in (await ctx.db.execute(stmt)).scalars().all():
        if closed >= ENTRY_SLIP_COUNT:
            break
        if record.student_id not in enrolled:
            continue
        absence_day = record.context.date if record.context else today
        try:
            slip = await entry_slip_service.compose(
                ctx.db,
                record.id,
                resume_date=absence_day + timedelta(days=1),
                notes=_SLIP_NOTE,
            )
            await entry_slip_service.close_absence(ctx.db, slip, actor_id=actor)
        except Exception as error:  # noqa: BLE001
            await ctx.db.rollback()
            logger.warning("Billet d'entrée non délivré sur l'appel %s : %s", record.id, error)
            continue
        closed += 1
        ctx.tally("billets d'entrée")


async def ensure_file_requests(ctx: SeedContext) -> None:
    """Des demandes de dossier vers les établissements d'origine.

    Seuls les élèves venus d'ailleurs en reçoivent une : c'est le collège
    précédent qu'on écrit, et un élève qui n'en a pas n'a rien à réclamer. Le
    registre des émissions scellées sert de clé de rapprochement, pour ne pas
    réécrire chaque année le même courrier.
    """
    seals = select(DocumentIssuance.student_id).where(
        DocumentIssuance.document_type == school_file_request_service.DOCUMENT_TYPE
    )
    scelles = (await ctx.db.execute(seals)).scalars().all()
    # Le total prime : le registre des émissions ne porte pas toujours l'élève,
    # et compter les courriers déjà partis est le seul garde-fou qui tienne
    # d'une exécution à l'autre.
    if len(scelles) >= FILE_REQUEST_COUNT:
        return
    already = {int(row) for row in scelles if row is not None}

    stmt = (
        select(Student.id)
        .join(Enrollment, Enrollment.student_id == Student.id)
        .where(
            Student.previous_school.is_not(None),
            Student.enrollment_number.is_not(None),
            Enrollment.academic_year_id == ctx.academic_year_id,
            Enrollment.status == EnrollmentStatus.VALIDE,
        )
        .order_by(Student.id)
    )
    actor = ctx.staff_user_by_role.get("staff") or ctx.actor_id
    sent = 0

    for student_id in (await ctx.db.execute(stmt)).scalars().all():
        if sent >= FILE_REQUEST_COUNT:
            break
        if student_id in already:
            continue
        try:
            await school_file_request_service.compose_request_data(
                ctx.db, student_id, actor_id=actor
            )
        except Exception as error:  # noqa: BLE001
            await ctx.db.rollback()
            logger.warning("Demande de dossier non émise pour l'élève %s : %s", student_id, error)
            continue
        sent += 1
        ctx.tally("demandes de dossier scolaire")


async def run(ctx: SeedContext) -> None:
    await ensure_summons(ctx)
    await ensure_retakes(ctx)
    await ensure_entry_slips(ctx)
    await ensure_file_requests(ctx)
