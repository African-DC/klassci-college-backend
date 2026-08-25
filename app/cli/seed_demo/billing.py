"""La grille tarifaire du collège pilote et son échéancier.

Deux idées à garder en tête en relisant ce module.

**La scolarité n'est due que par les non affectés.** Un élève affecté par
l'État dans un établissement privé est subventionné : sa famille paie
l'inscription, la tenue et les frais d'examen, mais pas la scolarité. Le
logiciel exprime cela par la portée du tarif, et non par une remise, ce qui
évite d'avoir à justifier un rabais élève par élève.

**Configurer une grille, c'est aussi retirer l'ancienne.** Une base de
démonstration porte des catégories héritées : trois « Scolarité Trimestre N »
d'un modèle abandonné : qui continueraient de se facturer par-dessus la
nouvelle grille. Le semis les met **hors grille** (`is_mandatory = 0`). Rien
n'est supprimé : les lignes déjà facturées, les versements et l'historique
restent intacts, et un clic dans l'écran Frais suffit à les réactiver.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select

from app.cli.seed_demo import plan
from app.cli.seed_demo.context import SeedContext, logger
from app.models.fee import FeeAssignmentScope, FeeCategory, FeeVariant
from app.schemas.fee import FeeCategoryCreate, FeeVariantCreate
from app.schemas.installment import FeeInstallmentGridUpdate, FeeInstallmentInput
from app.services import fee_service
from app.services.installments import replace_grid


async def ensure_categories(ctx: SeedContext) -> None:
    """Les cinq natures de frais de la brochure, dans leur ordre d'imputation."""
    existing = {
        plan.normalize(row.name): row
        for row in (await ctx.db.execute(select(FeeCategory))).scalars().all()
    }

    for name, priority, description in plan.FEE_CATEGORIES:
        found = existing.get(plan.normalize(name))
        if found is None:
            response = await fee_service.create_fee_category(
                ctx.db,
                FeeCategoryCreate(
                    name=name, description=description, is_mandatory=True, priority=priority
                ),
                created_by=ctx.actor_id,
            )
            ctx.fee_category_ids[name] = response.id
            ctx.tally("catégories de frais")
        else:
            ctx.fee_category_ids[name] = found.id
            found.priority = priority
            found.is_mandatory = True
            found.description = found.description or description

    await ctx.db.commit()


async def retire_off_grid_categories(ctx: SeedContext) -> None:
    """Sort de la grille toute catégorie obligatoire que la brochure n'annonce pas.

    Sans ce passage, un élève de 6e se verrait facturer la scolarité de la
    grille **et** les trois trimestres du modèle précédent : 288 000 F au lieu
    de 125 000, et un taux de recouvrement qui ne veut plus rien dire.
    """
    kept = {plan.normalize(name) for name, _priority, _description in plan.FEE_CATEGORIES}
    rows = (
        (await ctx.db.execute(select(FeeCategory).where(FeeCategory.is_mandatory.is_(True))))
        .scalars()
        .all()
    )

    for row in rows:
        if plan.normalize(row.name) in kept:
            continue
        logger.info("Catégorie « %s » sortie de la grille obligatoire.", row.name)
        row.is_mandatory = False
        ctx.tally("catégories sorties de la grille")

    await ctx.db.commit()


async def ensure_variants(ctx: SeedContext) -> None:
    """Un tarif par (catégorie, niveau) pour l'année, portée comprise.

    On modifie le montant d'un tarif déjà saisi plutôt que d'en ajouter un
    second : la contrainte d'unicité de la base l'imposerait de toute façon, et
    une grille qui existe en double n'a plus de prix.
    """
    rows = (
        (
            await ctx.db.execute(
                select(FeeVariant).where(FeeVariant.academic_year_id == ctx.academic_year_id)
            )
        )
        .scalars()
        .all()
    )
    by_key = {
        (row.fee_category_id, row.level_id, row.series_id, row.assignment_scope): row
        for row in rows
    }

    for level, _order, _aliases in plan.LEVELS:
        level_id = ctx.level_ids[level]
        for name, amount in plan.fees_for_level(level).items():
            category_id = ctx.fee_category_ids[name]
            scope = FeeAssignmentScope.NON_AFFECTE if name in plan.NON_AFFECTED_ONLY else None
            found = by_key.get((category_id, level_id, None, scope.value if scope else None))
            if found is not None:
                if found.amount != amount:
                    found.amount = amount
                    ctx.tally("tarifs mis à jour")
                continue

            await fee_service.create_fee_variant(
                ctx.db,
                FeeVariantCreate(
                    fee_category_id=category_id,
                    level_id=level_id,
                    academic_year_id=ctx.academic_year_id,
                    amount=amount,
                    assignment_scope=scope,
                    description=f"{name} : {level}",
                ),
                created_by=ctx.actor_id,
            )
            ctx.tally("tarifs")

    await ctx.db.commit()


def _installment_lines(year_start: int) -> list[FeeInstallmentInput]:
    """La grille de tranches, datée sur l'année scolaire visée.

    Les échéances de janvier et de mars tombent l'année civile suivante : une
    grille dont toutes les dates sont dans la même année civile décalerait tout
    l'échéancier d'un an et rendrait chaque famille en avance.
    """
    lines: list[FeeInstallmentInput] = []
    for name, position, is_fixed, value, month, day in plan.INSTALLMENT_GRID:
        calendar_year = year_start if month >= 9 else year_start + 1
        lines.append(
            FeeInstallmentInput(
                name=name,
                position=position,
                kind="fixed" if is_fixed else "percentage",
                amount=float(value) if is_fixed else None,
                percentage=None if is_fixed else float(value),
                due_date=date(calendar_year, month, day),
            )
        )
    return lines


async def ensure_installment_grid(ctx: SeedContext) -> None:
    """L'échéancier annoncé aux familles : inscription ferme, puis 35/35/30 %.

    C'est lui qui décide qui est « en retard », donc qui voit son certificat de
    scolarité retenu. Une grille dont les dates appartiennent à une autre année
    déclarerait toute l'école à jour, ce qui ne se démontre pas.
    """
    year_start = int(ctx.academic_year_name.split("-")[0])
    await replace_grid(
        ctx.db,
        ctx.academic_year_id,
        FeeInstallmentGridUpdate(installments=_installment_lines(year_start)),
        updated_by=ctx.actor_id,
    )
    ctx.tally("tranches", len(plan.INSTALLMENT_GRID))


async def run(ctx: SeedContext) -> None:
    await ensure_categories(ctx)
    await retire_off_grid_categories(ctx)
    await ensure_variants(ctx)
    await ensure_installment_grid(ctx)
