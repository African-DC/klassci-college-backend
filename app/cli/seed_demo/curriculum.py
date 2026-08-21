"""Les matières : un catalogue, puis une instance par niveau et par série.

Le catalogue tient le nom, les instances tiennent le coefficient : parce que le
même français ne pèse pas pareil en 6e et en Terminale A. C'est l'instance qui
porte l'enseignant, et c'est par elle que passent les évaluations, l'emploi du
temps et les bulletins.
"""

from __future__ import annotations

from sqlalchemy import select

from app.cli.seed_demo import plan
from app.cli.seed_demo.context import SeedContext
from app.models.academic import Subject
from app.schemas.admin import SubjectCreate
from app.services import admin_service

#: Une couleur par matière, pour que l'emploi du temps se lise d'un coup d'œil.
COLORS: dict[str, str] = {
    "Français": "#B91C1C",
    "Mathématiques": "#1D4ED8",
    "Anglais": "#7C3AED",
    "Histoire-Géographie": "#B45309",
    "Sciences de la Vie et de la Terre": "#15803D",
    "Physique-Chimie": "#0E7490",
    "Philosophie": "#4C1D95",
    "Espagnol": "#DB2777",
    "Allemand": "#334155",
    "Éducation Physique et Sportive": "#EA580C",
}


def _teacher_for(ctx: SeedContext, subject: str, rotation: int) -> int | None:
    """Répartit les classes entre les enseignants d'une même matière.

    Un tourniquet plutôt qu'un tirage : deux exécutions doivent attribuer les
    mêmes classes aux mêmes professeurs, sans quoi l'emploi du temps changerait
    de titulaire à chaque relance.
    """
    pool = ctx.teachers_by_subject.get(subject)
    if not pool:
        return None
    return pool[rotation % len(pool)]


async def ensure_catalogue(ctx: SeedContext) -> None:
    """Le catalogue : une ligne par matière, sans niveau ni série."""
    existing = {
        plan.normalize(name)
        for name in (await ctx.db.execute(select(Subject.name).where(Subject.level_id.is_(None))))
        .scalars()
        .all()
    }
    for name in plan.all_subject_names():
        if plan.normalize(name) in existing:
            continue
        await admin_service.create_subject(
            ctx.db,
            SubjectCreate(name=name, coefficient=1, hours_per_week=2, color=COLORS.get(name)),
            created_by=ctx.actor_id,
        )
        ctx.tally("matières (catalogue)")


async def ensure_instances(ctx: SeedContext) -> None:
    """Une instance par (niveau, série, matière), avec son coefficient réel."""
    rows = (
        (await ctx.db.execute(select(Subject).where(Subject.level_id.is_not(None)))).scalars().all()
    )
    by_key = {(row.level_id, row.series_id, plan.normalize(row.name)): row for row in rows}

    rotation = 0
    for level, serie, _division in plan.class_plan():
        level_id = ctx.level_ids[level]
        series_id = ctx.series_ids[(level, serie)] if serie else None
        rotation += 1

        for name, coefficient, weekly in plan.curriculum_for(level, serie):
            key = (level_id, series_id, plan.normalize(name))
            teacher_id = _teacher_for(ctx, name, rotation)
            found = by_key.get(key)

            if found is None:
                response = await admin_service.create_subject(
                    ctx.db,
                    SubjectCreate(
                        name=name,
                        level_id=level_id,
                        series_id=series_id,
                        coefficient=coefficient,
                        hours_per_week=weekly,
                        color=COLORS.get(name),
                        teacher_id=teacher_id,
                    ),
                    created_by=ctx.actor_id,
                )
                ctx.subject_ids[(level, serie, name)] = response.id
                ctx.tally("matières (instances)")
            else:
                ctx.subject_ids[(level, serie, name)] = found.id
                # Une instance sans titulaire ne peut porter ni évaluation ni
                # créneau : on la complète, sans jamais déloger un enseignant
                # que l'école a désigné elle-même.
                if found.teacher_id is None and teacher_id is not None:
                    found.teacher_id = teacher_id
                if found.color is None:
                    found.color = COLORS.get(name)

    await ctx.db.commit()


async def run(ctx: SeedContext) -> None:
    await ensure_catalogue(ctx)
    await ensure_instances(ctx)
