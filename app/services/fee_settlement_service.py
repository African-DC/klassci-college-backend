"""Charger le tableau des soldes, et le rendre en classeur.

Séparé des formes pour la raison qui a fait séparer le journal des versements
des siennes : la fabrique de classeur importe les formes, et si les formes
importaient la fabrique, le cycle se refermerait. Ici l'import est descendant
et normal.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.enrollment import CLOSED_STATUSES, Enrollment
from app.models.fee import FeeCategory
from app.models.user import Student
from app.services import fees_paid
from app.services._school_settings_helper import load_school_settings_for_pdf
from app.services.exports.fee_settlement_xlsx import generate_fee_settlement_xlsx
from app.services.fee_settlement import (
    FeeLineInput,
    RowInput,
    SettlementMatrix,
    build_matrix,
)


async def load_settlement(
    db: AsyncSession, *, academic_year_id: int, class_id: int | None = None
) -> SettlementMatrix:
    """Charge les inscriptions de l'annee, et compose leur tableau.

    **La classe est facultative.** La question posee est « ou en est chaque
    famille sur ce frais », a l'echelle de l'ecole ; la classe ne fait que
    reduire quand on veut regarder de plus pres. L'exiger forcait a parcourir
    les classes une par une, ce que cet ecran existe pour eviter.

    Trois requêtes, quel que soit l'effectif : les inscriptions avec leurs
    frais, les catégories vues, et le versé par frais. `EnrollmentFee` ne porte
    pas de relation vers sa catégorie, seulement son identifiant — les lire une
    par frais coûterait une requête par élève et par ligne.

    Les dossiers rejetés et annulés sont écartés, comme sur la liste de saisie
    en lot : compter un élève qui n'est plus là parmi les non soldés ferait
    courir après quelqu'un qui ne doit rien.
    """
    conditions = [
        Enrollment.academic_year_id == academic_year_id,
        Enrollment.status.not_in(CLOSED_STATUSES),
    ]
    if class_id is not None:
        conditions.append(Enrollment.class_id == class_id)

    stmt = (
        select(Enrollment)
        .join(Student, Student.id == Enrollment.student_id)
        .where(*conditions)
        .options(
            selectinload(Enrollment.student),
            selectinload(Enrollment.enrollment_fees),
            selectinload(Enrollment.class_),
            selectinload(Enrollment.academic_year),
        )
        .order_by(Student.last_name, Student.first_name, Enrollment.id)
    )
    inscriptions = list((await db.execute(stmt)).scalars().all())

    ids = {frais.fee_category_id for i in inscriptions for frais in i.enrollment_fees}
    categories: dict[int, FeeCategory] = {}
    if ids:
        categories = {
            c.id: c
            for c in (
                await db.execute(select(FeeCategory).where(FeeCategory.id.in_(ids)))
            ).scalars()
        }

    paid_by_fee = await fees_paid.paid_for_scope(
        db, academic_year_id=academic_year_id, class_id=class_id
    )

    premiere = inscriptions[0] if inscriptions else None
    return build_matrix(
        (
            RowInput(
                enrollment_id=inscription.id,
                student_id=inscription.student.id,
                first_name=inscription.student.first_name,
                last_name=inscription.student.last_name,
                # Le matricule vit sous `enrollment_number`, comme partout
                # ailleurs : `matricule` n'existe pas sur le modèle, et un
                # `getattr` sur ce nom-là aurait rendu `None` en silence.
                student_matricule=getattr(inscription.student, "enrollment_number", None),
                # Sur toute l'ecole, la classe situe l'eleve : sans elle, deux
                # homonymes de niveaux differents seraient impossibles a
                # departager sur une liste de quatre-vingt-dix-neuf lignes.
                class_name=getattr(inscription.class_, "name", "") or "",
                fees=tuple(
                    FeeLineInput(
                        fee_id=frais.id,
                        category_id=frais.fee_category_id,
                        status=str(getattr(frais.status, "value", frais.status)),
                        amount=Decimal(str(frais.amount or 0)),
                    )
                    for frais in inscription.enrollment_fees
                ),
            )
            for inscription in inscriptions
        ),
        categories=categories,
        paid_by_fee=paid_by_fee,
        class_name=(
            getattr(getattr(premiere, "class_", None), "name", "") or ""
            if class_id is not None
            else "Toutes les classes"
        ),
        academic_year_name=getattr(getattr(premiere, "academic_year", None), "name", "") or "",
    )


async def get_settlement_xlsx(
    db: AsyncSession, *, academic_year_id: int, class_id: int | None = None
) -> bytes:
    """Le tableau de la classe, au gabarit officiel de l'établissement."""
    matrix = await load_settlement(db, academic_year_id=academic_year_id, class_id=class_id)
    school = await load_school_settings_for_pdf(db)
    return generate_fee_settlement_xlsx(matrix, school)
