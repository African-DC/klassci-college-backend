"""Qui a soldé quelle catégorie de frais, une classe à la fois.

L'état des frais existe déjà par élève : la fiche d'inscription montre chaque
catégorie avec son statut, lignes déposées en nature comprises. Il n'existait
nulle part par classe. Pour savoir qui a soldé la scolarité et qui n'a pas
encore remis sa tenue, il fallait ouvrir les fiches une par une — soixante-dix
huit fiches, le même travail qui ne se termine pas et qui avait déjà justifié
la saisie en lot.

Le journal des versements ne répond pas à la question. Il liste des versements,
pas des élèves : celui qui n'a jamais rien versé n'y figure pas du tout, alors
que c'est précisément celui qu'on cherche.

Deux distinctions portent tout le reste, et les confondre viderait le tableau
de son intérêt :

- **soldé en argent** et **déposé en nature** sont deux façons de ne plus rien
  devoir, mais l'école ne les traite pas pareil. Les fondre en un seul « OK »
  ferait disparaître la question « a-t-il remis sa tenue ? ».
- **dû** et **partiel** se distinguent parce qu'on ne relance pas avec les
  mêmes mots une famille qui a déjà versé la moitié.

La composition est une fonction pure, la lecture de la base une autre : le
tableau se teste sans base, comme le journal des versements dont ce module
reprend la découpe.
"""

from __future__ import annotations

import enum
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.enrollment import CLOSED_STATUSES, Enrollment
from app.models.fee import FeeCategory, cash_remaining, is_in_kind, is_not_cash_due
from app.models.user import Student
from app.schemas.payment import (
    SettlementCellResponse,
    SettlementColumnResponse,
    SettlementMatrixResponse,
    SettlementRowResponse,
)
from app.services import fees_paid

#: Rang des catégories qui n'en portent pas, comme dans l'état des frais.
_PRIORITE_PAR_DEFAUT = 100


class SettlementState(str, enum.Enum):
    """L'état d'une catégorie pour un élève, tel que la case l'affiche."""

    #: Soldé en argent.
    PAID = "paid"
    #: Une partie versée, une partie encore due.
    PARTIAL = "partial"
    #: Rien versé, tout dû.
    PENDING = "pending"
    #: Réglé par un dépôt en nature, jamais par de l'argent.
    IN_KIND = "in_kind"
    #: L'école a renoncé à ce montant.
    WAIVED = "waived"
    #: Cette inscription ne porte pas cette catégorie. Ce n'est pas un impayé.
    ABSENT = "absent"


#: Ce que chaque état s'appelle dans un document. L'export est la seule sortie
#: qui compose ces mots côté serveur — l'écran a les siens — mais il les compose
#: à partir de l'énumération, pour qu'un état ajouté demain n'y sorte pas vide.
STATE_LABEL: dict[SettlementState, str] = {
    SettlementState.PAID: "Soldé",
    SettlementState.PARTIAL: "Partiel",
    SettlementState.PENDING: "Dû",
    SettlementState.IN_KIND: "En nature",
    SettlementState.WAIVED: "Exonéré",
    SettlementState.ABSENT: "—",
}

#: Les états qui ne doivent plus rien. `ABSENT` en fait partie : un élève ne
#: peut pas être en retard sur un frais qu'on ne lui a jamais facturé.
SETTLED_STATES = frozenset(
    {
        SettlementState.PAID,
        SettlementState.IN_KIND,
        SettlementState.WAIVED,
        SettlementState.ABSENT,
    }
)


@dataclass(frozen=True, slots=True)
class SettlementColumn:
    """Une colonne : la catégorie de frais, telle qu'elle est facturée ici."""

    category_id: int
    name: str
    priority: int


@dataclass(frozen=True, slots=True)
class SettlementCell:
    """Une case : ce que cet élève doit sur cette catégorie, et où il en est."""

    category_id: int
    state: SettlementState
    due: Decimal
    paid: Decimal
    remaining: Decimal


@dataclass(frozen=True, slots=True)
class SettlementRow:
    """Une ligne : un élève, et son état sur chaque colonne."""

    enrollment_id: int
    student_id: int
    # Nom et prénom séparés, comme la liste de saisie en lot : deux écrans qui
    # montrent la même classe ne doivent pas composer le nom chacun à sa façon.
    first_name: str
    last_name: str
    student_matricule: str | None
    cells: tuple[SettlementCell, ...]

    @property
    def settled(self) -> bool:
        """Vrai quand plus rien n'est dû, dépôts en nature compris."""
        return all(cell.state in SETTLED_STATES for cell in self.cells)


@dataclass(frozen=True, slots=True)
class SettlementMatrix:
    """Le tableau complet, prêt à afficher ou à exporter."""

    columns: tuple[SettlementColumn, ...]
    rows: tuple[SettlementRow, ...]
    class_name: str
    academic_year_name: str

    @property
    def settled_count(self) -> int:
        return sum(1 for row in self.rows if row.settled)

    @property
    def total_count(self) -> int:
        return len(self.rows)


@dataclass(frozen=True, slots=True)
class FeeLineInput:
    """Un frais d'une inscription, réduit à ce dont le tableau a besoin."""

    fee_id: int
    category_id: int
    status: str
    amount: Decimal


@dataclass(frozen=True, slots=True)
class RowInput:
    """Une inscription, réduite de même."""

    enrollment_id: int
    student_id: int
    first_name: str
    last_name: str
    student_matricule: str | None
    fees: tuple[FeeLineInput, ...]


def resolve_cell(
    category_id: int, lines: Sequence[FeeLineInput], paid_by_fee: dict[int, Decimal]
) -> SettlementCell:
    """L'état d'une catégorie pour un élève, toutes ses lignes réunies.

    Une catégorie peut porter plusieurs lignes — trois tranches de scolarité,
    par exemple. La case doit alors répondre pour l'ensemble : afficher l'état
    de la première tranche dirait « soldé » à une famille qui doit encore les
    deux suivantes.

    L'ordre des tests n'est pas indifférent. **Ce qui reste dû l'emporte sur
    tout le reste** : un élève qui a déposé sa tenue mais n'a pas fini de payer
    sa scolarité est en retard, et une case « déposé » le sortirait des
    relances. À l'inverse, quand plus rien n'est dû, on nomme la façon dont
    la ligne s'est éteinte, parce que « soldé en argent » et « déposé » ne se
    traitent pas pareil.
    """
    due = Decimal("0")
    paid = Decimal("0")
    remaining = Decimal("0")
    porte_du_nature = False
    porte_une_exoneration = False

    for line in lines:
        verse = paid_by_fee.get(line.fee_id, Decimal("0"))
        remaining += cash_remaining(line.status, line.amount, verse)
        if is_in_kind(line.status):
            porte_du_nature = True
            continue
        if is_not_cash_due(line.status):
            porte_une_exoneration = True
            continue
        # Une ligne exonérée sort du dû comme du versé : garder son montant
        # ferait apparaître une dette que l'école a explicitement annulée.
        due += line.amount
        paid += verse

    if not lines:
        state = SettlementState.ABSENT
    elif remaining > 0:
        state = SettlementState.PARTIAL if paid > 0 else SettlementState.PENDING
    elif paid > 0:
        state = SettlementState.PAID
    elif porte_du_nature:
        state = SettlementState.IN_KIND
    elif porte_une_exoneration:
        state = SettlementState.WAIVED
    else:
        # Plus rien à devoir sans qu'un franc ait circulé : un frais à zéro.
        state = SettlementState.PAID

    return SettlementCell(
        category_id=category_id, state=state, due=due, paid=paid, remaining=remaining
    )


def build_matrix(
    rows: Iterable[RowInput],
    *,
    categories: dict[int, FeeCategory],
    paid_by_fee: dict[int, Decimal],
    class_name: str,
    academic_year_name: str,
) -> SettlementMatrix:
    """Compose le tableau à partir de données déjà chargées.

    Les colonnes sont **les catégories réellement portées par la classe**, et
    pas la grille tarifaire entière : une colonne vide sur quarante élèves
    n'apprend rien et pousse le tableau hors de l'écran.
    """
    rows = list(rows)

    ids_vus = {fee.category_id for row in rows for fee in row.fees}
    colonnes = tuple(
        sorted(
            (
                SettlementColumn(
                    category_id=cid,
                    name=getattr(categories.get(cid), "name", "") or f"Catégorie {cid}",
                    priority=getattr(categories.get(cid), "priority", _PRIORITE_PAR_DEFAUT)
                    or _PRIORITE_PAR_DEFAUT,
                )
                for cid in ids_vus
            ),
            key=lambda col: (col.priority, col.name),
        )
    )

    lignes: list[SettlementRow] = []
    for row in rows:
        par_categorie: dict[int, list[FeeLineInput]] = {}
        for fee in row.fees:
            par_categorie.setdefault(fee.category_id, []).append(fee)
        lignes.append(
            SettlementRow(
                enrollment_id=row.enrollment_id,
                student_id=row.student_id,
                first_name=row.first_name,
                last_name=row.last_name,
                student_matricule=row.student_matricule,
                cells=tuple(
                    resolve_cell(
                        col.category_id, par_categorie.get(col.category_id, []), paid_by_fee
                    )
                    for col in colonnes
                ),
            )
        )

    return SettlementMatrix(
        columns=colonnes,
        rows=tuple(lignes),
        class_name=class_name,
        academic_year_name=academic_year_name,
    )


async def load_settlement(
    db: AsyncSession, *, class_id: int, academic_year_id: int
) -> SettlementMatrix:
    """Charge la classe et compose son tableau.

    Trois requêtes, quel que soit l'effectif : les inscriptions avec leurs
    frais, les catégories vues, et le versé par frais. `EnrollmentFee` ne porte
    pas de relation vers sa catégorie, seulement son identifiant — les lire une
    par frais coûterait une requête par élève et par ligne.

    Les dossiers rejetés et annulés sont écartés, comme sur la liste de saisie
    en lot : compter un élève qui n'est plus là parmi les non soldés ferait
    courir après quelqu'un qui ne doit rien.
    """
    stmt = (
        select(Enrollment)
        .join(Student, Student.id == Enrollment.student_id)
        .where(
            Enrollment.class_id == class_id,
            Enrollment.academic_year_id == academic_year_id,
            Enrollment.status.not_in(CLOSED_STATUSES),
        )
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

    paid_by_fee = await fees_paid.paid_by_class(
        db, class_id=class_id, academic_year_id=academic_year_id
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
        class_name=getattr(getattr(premiere, "class_", None), "name", "") or "",
        academic_year_name=getattr(getattr(premiere, "academic_year", None), "name", "") or "",
    )


def to_response(matrix: SettlementMatrix) -> SettlementMatrixResponse:
    """Le tableau tel que l'API le rend.

    Les montants voyagent avec l'état plutôt que d'être recalculés par
    l'écran : une case « partiel » sans le reste dû obligerait le frontend à
    refaire la soustraction, et deux calculs du même chiffre finissent
    toujours par en contredire un.
    """
    return SettlementMatrixResponse(
        class_name=matrix.class_name,
        academic_year_name=matrix.academic_year_name,
        columns=[
            SettlementColumnResponse(
                category_id=col.category_id, name=col.name, priority=col.priority
            )
            for col in matrix.columns
        ],
        rows=[
            SettlementRowResponse(
                enrollment_id=row.enrollment_id,
                student_id=row.student_id,
                first_name=row.first_name,
                last_name=row.last_name,
                student_matricule=row.student_matricule,
                cells=[
                    SettlementCellResponse(
                        category_id=cell.category_id,
                        state=cell.state.value,
                        due=cell.due,
                        paid=cell.paid,
                        remaining=cell.remaining,
                    )
                    for cell in row.cells
                ],
                settled=row.settled,
            )
            for row in matrix.rows
        ],
        settled_count=matrix.settled_count,
        total_count=matrix.total_count,
    )


async def get_settlement_xlsx(db: AsyncSession, *, class_id: int, academic_year_id: int) -> bytes:
    """Le tableau de la classe, au gabarit officiel de l'établissement."""
    # Import local, et seulement ici : la fabrique de classeur importe les
    # formes définies plus haut, et l'importer au chargement du module fermerait
    # le cycle. Le journal des versements sépare ses formes de son service pour
    # la même raison ; ce tableau n'a qu'un fichier, et paie la même dette d'une
    # ligne plutôt que d'un module.
    from app.services._school_settings_helper import load_school_settings_for_pdf
    from app.services.exports.fee_settlement_xlsx import generate_fee_settlement_xlsx

    matrix = await load_settlement(db, class_id=class_id, academic_year_id=academic_year_id)
    school = await load_school_settings_for_pdf(db)
    return generate_fee_settlement_xlsx(matrix, school)
