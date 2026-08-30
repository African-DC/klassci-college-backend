"""Le récapitulatif chiffré, relu à la source plutôt qu'aux compteurs.

Les compteurs du semis disent ce que l'exécution vient d'écrire ; ce module dit
ce que la base contient. Les deux divergent dès la seconde exécution, et c'est
le second chiffre qui intéresse quelqu'un qui prépare une présentation.

Le taux de recouvrement se calcule avec **les fonctions de l'application**, pas
avec une requête maison : un taux de démonstration qui ne serait pas celui du
tableau de bord se verrait à la première diapositive.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select

from app.cli.seed_demo.context import SeedContext
from app.models.academic import Class
from app.models.enrollment import Enrollment, EnrollmentStatus
from app.models.fee import (
    NOT_CASH_DUE,
    EnrollmentFee,
    FeeCategory,
    FeeVariant,
    Payment,
    PaymentStatus,
)
from app.models.grade import Bulletin, Grade
from app.models.user import Student
from app.services import fees_paid


async def _count(ctx: SeedContext, statement: object) -> int:
    return int((await ctx.db.execute(statement)).scalar_one() or 0)


async def expected_mandatory_total(ctx: SeedContext) -> Decimal:
    """Ce que l'école attend sur l'année, au même périmètre que l'encaissé.

    Frais obligatoires, non exonérés : exactement le périmètre de
    `fees_paid.paid_on_mandatory_for_year`. Élargir l'un sans l'autre ferait un
    taux de recouvrement qui ne veut rien dire.
    """
    statement = (
        select(func.coalesce(func.sum(EnrollmentFee.amount), 0))
        .join(FeeVariant, FeeVariant.id == EnrollmentFee.fee_variant_id)
        .join(FeeCategory, FeeCategory.id == FeeVariant.fee_category_id)
        .join(Enrollment, Enrollment.id == EnrollmentFee.enrollment_id)
        .where(
            Enrollment.academic_year_id == ctx.academic_year_id,
            FeeCategory.is_mandatory.is_(True),
            EnrollmentFee.status.notin_(NOT_CASH_DUE),
        )
    )
    return Decimal(str((await ctx.db.execute(statement)).scalar_one() or 0))


async def figures(ctx: SeedContext) -> dict[str, object]:
    """Les chiffres que l'on montre après le semis."""
    year = ctx.academic_year_id

    enrolled = (
        select(func.count()).select_from(Enrollment).where(Enrollment.academic_year_id == year)
    )
    validated = enrolled.where(Enrollment.status == EnrollmentStatus.VALIDE.value)

    students = (
        select(func.count(func.distinct(Enrollment.student_id)))
        .select_from(Enrollment)
        .where(Enrollment.academic_year_id == year)
    )
    classes = (
        select(func.count(func.distinct(Enrollment.class_id)))
        .select_from(Enrollment)
        .where(Enrollment.academic_year_id == year)
    )

    grades = select(func.count()).select_from(Grade).where(Grade.value.is_not(None))
    bulletins = select(func.count()).select_from(Bulletin).where(Bulletin.academic_year_id == year)
    published = bulletins.where(Bulletin.is_published.is_(True))

    payments = (
        select(func.count())
        .select_from(Payment)
        .join(Enrollment, Enrollment.id == Payment.enrollment_id)
        .where(
            Enrollment.academic_year_id == year,
            Payment.status == PaymentStatus.COMPLETED.value,
        )
    )

    expected = await expected_mandatory_total(ctx)
    collected = await fees_paid.paid_on_mandatory_for_year(ctx.db, year)
    rate = (collected / expected * 100) if expected else Decimal("0")

    return {
        "année scolaire": ctx.academic_year_name,
        "élèves": await _count(ctx, students),
        "élèves (fiches totales)": await _count(ctx, select(func.count()).select_from(Student)),
        "classes servies": await _count(ctx, classes),
        "classes (référentiel)": await _count(ctx, select(func.count()).select_from(Class)),
        "inscriptions": await _count(ctx, enrolled),
        "inscriptions validées": await _count(ctx, validated),
        "notes saisies": await _count(ctx, grades),
        "bulletins": await _count(ctx, bulletins),
        "bulletins publiés": await _count(ctx, published),
        "versements": await _count(ctx, payments),
        "total attendu (XOF)": expected,
        "total encaissé (XOF)": collected,
        "taux de recouvrement (%)": rate.quantize(Decimal("0.1")),
    }


def render(values: dict[str, object]) -> str:
    """Le récapitulatif tel qu'il s'affiche en fin d'exécution."""
    width = max(len(label) for label in values)
    lines = [f"  {label.ljust(width)} : {value}" for label, value in values.items()]
    return "\n".join(lines)
