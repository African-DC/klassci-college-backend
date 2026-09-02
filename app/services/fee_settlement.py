"""Qui a soldé quelle catégorie de frais : les formes, et leur composition.

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

**Ce fichier ne touche ni la base ni les documents.** Il porte les formes et la
composition, rien d'autre : `fee_settlement_service` les charge, la fabrique de
classeur les rend. C'est la découpe du journal des versements, pour la même
raison — la composition se teste alors sans base, et la fabrique peut importer
les formes sans refermer un cycle sur le service.
"""

from __future__ import annotations

import enum
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal

from app.models.fee import FeeCategory, cash_remaining, is_in_kind, is_not_cash_due

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
    #: Situe l'élève quand le tableau couvre toute l'école.
    class_name: str
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
    class_name: str
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
                class_name=row.class_name,
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
