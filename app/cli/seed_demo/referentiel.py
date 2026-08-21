"""Le référentiel : année scolaire, niveaux, séries, classes, salles, identité.

Tout y est **résolu avant d'être créé**. Un établissement de démonstration n'est
jamais vierge : il porte déjà une « Terminal » sans e, une « 1ere C » sans
accent, une « Seconde » là où le semis dit « 2nde ». Créer par-dessus
produirait deux Terminales et deux listes d'appel. On rapproche donc sur le
libellé normalisé, et on ne crée que ce qui manque vraiment.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import func, select

from app.cli.seed_demo import plan
from app.cli.seed_demo.context import SeedContext, logger
from app.models.academic import (
    AcademicYear,
    Class,
    Level,
    Room,
    SchoolHoliday,
    SchoolSettings,
    Series,
    Trimester,
)
from app.models.enrollment import Enrollment, EnrollmentStatus
from app.schemas.admin import (
    AcademicYearCreate,
    ClassCreate,
    LevelCreate,
    RoomCreate,
    SeriesCreate,
)
from app.services import admin_service

#: Année scolaire de la démonstration. Elle est **terminée** : la présentation
#: montre une année vécue de bout en bout, bulletins des trois trimestres
#: compris, pas une rentrée qui vient d'ouvrir.
YEAR_NAME = "2025-2026"
YEAR_START = date(2025, 9, 1)
YEAR_END = date(2026, 6, 30)
NEXT_YEAR_NAME = "2026-2027"

TRIMESTERS: tuple[tuple[str, int, date, date], ...] = (
    ("1er trimestre", 1, date(2025, 9, 1), date(2025, 12, 19)),
    ("2e trimestre", 2, date(2026, 1, 5), date(2026, 4, 3)),
    ("3e trimestre", 3, date(2026, 4, 13), date(2026, 6, 30)),
)

HOLIDAYS: tuple[tuple[str, date, date], ...] = (
    ("Congés de Toussaint", date(2025, 10, 27), date(2025, 11, 2)),
    ("Congés de Noël", date(2025, 12, 20), date(2026, 1, 4)),
    ("Congés de détente", date(2026, 2, 16), date(2026, 2, 22)),
    ("Lundi de Pâques", date(2026, 4, 6), date(2026, 4, 6)),
    ("Fête du Travail", date(2026, 5, 1), date(2026, 5, 1)),
    ("Fête nationale", date(2026, 8, 7), date(2026, 8, 7)),
)

#: Identité de l'établissement pilote. Elle alimente l'en-tête de tous les
#: documents officiels : sans elle, les PDF sortent au nom de personne.
SCHOOL_IDENTITY: dict[str, str] = {
    "school_name": "Collège Privé Rostan",
    "address": "Angré 7e Tranche, Cocody, 08 BP 1245 Abidjan 08",
    "phone": "27-22-45-18-90// 07-58-59-97-73",
    "email": "secretariat@college-rostan.ci",
    "ministry_code": "CI-ABJ-0742",
    "drena_name": "ABIDJAN 4",
    "head_master_name": "M. Séraphin Kouamé Adjoumani",
    "head_master_title": "Directeur Général",
    "motto": "Union - Discipline - Travail",
    "secondary_motto": "Soyons des citoyens responsables pour une école de qualité",
    "website": "https://college-rostan.ci",
    "primary_color": "#1D4ED8",
    "accent_color": "#EA580C",
    "enrollment_number_pattern": "{SCHOOL}-{YEAR_SHORT}-{SEQ:04}",
    "enabled_payment_methods": "cash,mobile_money,bank_transfer,cheque",
}


async def ensure_academic_year(ctx: SeedContext) -> None:
    """L'année scolaire de la démonstration, ses trimestres et ses congés.

    L'année est marquée courante : une bonne moitié des services refuse de
    travailler sans, et le refus arriverait bien plus loin dans le semis.
    """
    year = (
        await ctx.db.execute(select(AcademicYear).where(AcademicYear.name == YEAR_NAME))
    ).scalar_one_or_none()
    if year is None:
        response = await admin_service.create_academic_year(
            ctx.db,
            AcademicYearCreate(
                name=YEAR_NAME, start_date=YEAR_START, end_date=YEAR_END, is_current=True
            ),
            created_by=ctx.actor_id,
        )
        ctx.academic_year_id = response.id
        ctx.tally("années scolaires")
    else:
        ctx.academic_year_id = year.id
        if not year.is_current:
            year.is_current = True
            await ctx.db.commit()

    ctx.academic_year_name = YEAR_NAME

    next_year = (
        await ctx.db.execute(select(AcademicYear).where(AcademicYear.name == NEXT_YEAR_NAME))
    ).scalar_one_or_none()
    if next_year is None:
        created = await admin_service.create_academic_year(
            ctx.db,
            AcademicYearCreate(
                name=NEXT_YEAR_NAME,
                start_date=date(2026, 9, 14),
                end_date=date(2027, 6, 30),
                is_current=False,
            ),
            created_by=ctx.actor_id,
        )
        ctx.next_year_id = created.id
        ctx.tally("années scolaires")
    else:
        ctx.next_year_id = next_year.id

    await _ensure_calendar(ctx)


async def _ensure_calendar(ctx: SeedContext) -> None:
    """Trimestres et congés : posés une seule fois, jamais réécrits.

    Un établissement en service a pu ajuster ses dates ; les recouvrir
    effacerait un arbitrage qu'un directeur a rendu.
    """
    existing = (
        (
            await ctx.db.execute(
                select(Trimester).where(Trimester.academic_year_id == ctx.academic_year_id)
            )
        )
        .scalars()
        .all()
    )

    if not existing:
        for label, order_no, start, end in TRIMESTERS:
            ctx.db.add(
                Trimester(
                    academic_year_id=ctx.academic_year_id,
                    label=label,
                    order_no=order_no,
                    start_date=start,
                    end_date=end,
                )
            )
            ctx.tally("trimestres")
        await ctx.db.commit()
        ctx.trimesters = [(order, start, end) for _label, order, start, end in TRIMESTERS]
    else:
        ctx.trimesters = sorted((t.order_no, t.start_date, t.end_date) for t in existing)

    holidays = (
        (
            await ctx.db.execute(
                select(SchoolHoliday).where(SchoolHoliday.academic_year_id == ctx.academic_year_id)
            )
        )
        .scalars()
        .all()
    )
    if not holidays:
        for label, start, end in HOLIDAYS:
            ctx.db.add(
                SchoolHoliday(
                    academic_year_id=ctx.academic_year_id,
                    label=label,
                    start_date=start,
                    end_date=end,
                )
            )
            ctx.tally("congés")
        await ctx.db.commit()


async def ensure_levels(ctx: SeedContext) -> None:
    """Les sept niveaux, retrouvés sous leurs graphies existantes.

    Le rang est corrigé quand il est faux : c'est lui qui ordonne toutes les
    listes de l'application, et une « première » rangée avant la 6e ferait
    ouvrir chaque écran sur le lycée.
    """
    existing = (await ctx.db.execute(select(Level))).scalars().all()
    by_key = {plan.normalize(level.name): level for level in existing}

    for canonical, order, _aliases in plan.LEVELS:
        found = next((by_key[key] for key in plan.level_aliases(canonical) if key in by_key), None)
        if found is None:
            response = await admin_service.create_level(
                ctx.db, LevelCreate(name=canonical, order=order), created_by=ctx.actor_id
            )
            ctx.level_ids[canonical] = response.id
            ctx.tally("niveaux")
            continue

        ctx.level_ids[canonical] = found.id
        if found.order != order:
            logger.info("Niveau « %s » : rang %s corrigé en %s", found.name, found.order, order)
            found.order = order
    await ctx.db.commit()


async def ensure_series(ctx: SeedContext) -> None:
    """Les séries de lycée, une seule par lettre et par niveau."""
    existing = (await ctx.db.execute(select(Series))).scalars().all()
    by_key = {(row.level_id, plan.series_token(row.name)): row for row in existing}

    for level, letters in plan.SERIES.items():
        level_id = ctx.level_ids[level]
        for letter in letters:
            found = by_key.get((level_id, letter))
            if found is None:
                response = await admin_service.create_series(
                    ctx.db, SeriesCreate(name=letter, level_id=level_id), created_by=ctx.actor_id
                )
                ctx.series_ids[(level, letter)] = response.id
                ctx.tally("séries")
            else:
                ctx.series_ids[(level, letter)] = found.id
    await ctx.db.commit()


async def ensure_classes(ctx: SeedContext) -> None:
    """Les divisions à ouvrir, rapprochées de celles qui existent déjà.

    Le rapprochement se fait sur le triplet (niveau, série, division) et non
    sur le nom : « Tle A » et « Terminale A » sont la même classe, et l'école
    tient à son libellé : on ne le réécrit pas.
    """
    existing = (await ctx.db.execute(select(Class))).scalars().all()
    by_key = {(row.level_id, row.series_id, plan.division_token(row.name)): row for row in existing}
    seated = await _seats_taken(ctx)

    for level, serie, division in plan.class_plan():
        level_id = ctx.level_ids[level]
        series_id = ctx.series_ids[(level, serie)] if serie else None
        planned = plan.class_size(level, serie, division) + plan.CLASS_HEADROOM

        found = by_key.get((level_id, series_id, division))
        if found is None:
            response = await admin_service.create_class(
                ctx.db,
                ClassCreate(
                    name=plan.class_display_name(level, division),
                    level_id=level_id,
                    series_id=series_id,
                    max_students=planned,
                ),
                created_by=ctx.actor_id,
            )
            ctx.class_ids[(level, serie, division)] = response.id
            ctx.tally("classes")
        else:
            ctx.class_ids[(level, serie, division)] = found.id
            # La classe accueille peut-être déjà des élèves saisis avant le
            # semis. Les places qu'ils occupent s'ajoutent à celles de la
            # cohorte, sinon l'inscription du trente-sixième élève se heurte à
            # une classe déclarée pleine et le semis s'arrête au milieu.
            capacity = planned + seated.get(found.id, 0)
            if found.max_students < capacity:
                found.max_students = capacity
    await ctx.db.commit()


async def _seats_taken(ctx: SeedContext) -> dict[int, int]:
    """Places déjà occupées dans chaque classe pour l'année visée."""
    statement = (
        select(Enrollment.class_id, func.count())
        .where(
            Enrollment.academic_year_id == ctx.academic_year_id,
            Enrollment.status.in_(
                (
                    EnrollmentStatus.VALIDE.value,
                    EnrollmentStatus.EN_VALIDATION.value,
                    EnrollmentStatus.PROSPECT.value,
                )
            ),
        )
        .group_by(Enrollment.class_id)
    )
    return {
        int(class_id): int(total) for class_id, total in (await ctx.db.execute(statement)).all()
    }


async def ensure_rooms(ctx: SeedContext) -> None:
    """Une salle par classe, plus les laboratoires.

    Modèle ivoirien : les élèves restent dans leur salle et ce sont les
    enseignants qui se déplacent. La salle porte donc le nom de la classe, et
    les rares laboratoires font exception.
    """
    await admin_service.batch_create_rooms_for_classes(ctx.db, created_by=ctx.actor_id)

    existing = {plan.normalize(row.name) for row in (await ctx.db.execute(select(Room))).scalars()}
    specials = (
        ("Laboratoire de Physique-Chimie", "laboratory", 40),
        ("Laboratoire de SVT", "laboratory", 40),
        ("Salle informatique", "computer_room", 30),
        ("Bibliothèque", "library", 60),
    )
    for name, room_type, capacity in specials:
        if plan.normalize(name) in existing:
            continue
        await admin_service.create_room(
            ctx.db,
            RoomCreate(name=name, room_type=room_type, capacity=capacity),
            created_by=ctx.actor_id,
        )
        ctx.tally("salles")


async def ensure_school_settings(ctx: SeedContext) -> None:
    """L'identité de l'établissement, sans laquelle les PDF sortent anonymes.

    On ne recouvre que les champs vides : une école qui a déjà saisi son nom
    et son cachet ne doit pas les voir remplacés par ceux de la démonstration.
    """
    settings_row = (await ctx.db.execute(select(SchoolSettings).limit(1))).scalar_one_or_none()
    if settings_row is None:
        settings_row = SchoolSettings(school_name=SCHOOL_IDENTITY["school_name"])
        ctx.db.add(settings_row)
        await ctx.db.flush()
        ctx.tally("paramètres d'établissement")

    for field, value in SCHOOL_IDENTITY.items():
        if not getattr(settings_row, field, None):
            setattr(settings_row, field, value)

    await ctx.db.commit()


async def run(ctx: SeedContext) -> None:
    """Pose le référentiel dans l'ordre où les dépendances l'exigent."""
    await ensure_academic_year(ctx)
    await ensure_levels(ctx)
    await ensure_series(ctx)
    await ensure_classes(ctx)
    await ensure_rooms(ctx)
    await ensure_school_settings(ctx)
