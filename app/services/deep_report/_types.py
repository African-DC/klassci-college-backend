"""Structures de données du rapport de fin de trimestre de la DEEP.

Le rapport est un empilement de tableaux. Plutôt que de laisser chaque
chapitre fabriquer son propre HTML, chacun produit des `ReportTable` neutres
que le générateur PDF sait rendre de façon uniforme. On gagne deux choses :
les calculs restent testables sans WeasyPrint, et l'habillage premium est
défini une seule fois.

Règle d'honnêteté, valable pour tout le module : une valeur qu'on ne sait pas
établir s'écrit `MISSING` (« — »), jamais zéro. Un zéro déposé à la DRENA se
lit comme un constat — « cet établissement n'a aucun boursier » — et non
comme une absence de saisie.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Cellule dont la valeur n'est pas connue. Volontairement distinct de "0".
MISSING = "—"

# Mention portée par tout tableau que KLASSCI ne sait pas remplir seul.
PENDING_NOTE = "À compléter manuellement"


@dataclass(frozen=True)
class HeaderGroup:
    """Une colonne, ou un groupe de colonnes sur deux niveaux d'en-tête.

    `subs` vide → colonne simple, fusionnée verticalement sur les deux lignes
    d'en-tête. `subs` renseigné → l'intitulé chapeaute ses sous-colonnes
    (« Effectifs réels » au-dessus de F / G / T).
    """

    label: str
    subs: tuple[str, ...] = ()
    align: str = "left"

    @property
    def width(self) -> int:
        return max(len(self.subs), 1)


def simple_headers(*labels: str, align: str = "left") -> tuple[HeaderGroup, ...]:
    """Raccourci pour un en-tête classique sur une seule ligne."""
    return tuple(HeaderGroup(label, align=align) for label in labels)


@dataclass(frozen=True)
class ReportRow:
    """Une ligne de tableau. `emphasis` marque les lignes de total."""

    cells: tuple[str, ...]
    emphasis: bool = False


@dataclass(frozen=True)
class ReportTable:
    """Un des 27 tableaux du canevas.

    `note` porte l'avertissement affiché sous le tableau — colonnes non
    collectées, inscriptions hors périmètre. C'est le canal d'honnêteté du
    document.

    `pending` distingue le tableau que la plateforme ne sait pas produire du
    tout de celui qui n'a simplement aucune ligne à montrer. Un drapeau, pas
    une recherche de texte dans la note : le rappel de fin de rapport ne doit
    pas dépendre d'une tournure de phrase.
    """

    number: int
    title: str
    groups: tuple[HeaderGroup, ...]
    rows: tuple[ReportRow, ...] = ()
    note: str | None = None
    pending: bool = False
    empty_message: str = MISSING
    # Le canevas répète certains tableaux une fois par classe : le numéro reste
    # celui du canevas, le sous-titre dit de quelle classe il s'agit.
    subtitle: str | None = None

    @property
    def column_count(self) -> int:
        return sum(group.width for group in self.groups)

    @property
    def has_grouped_header(self) -> bool:
        return any(group.subs for group in self.groups)


@dataclass(frozen=True)
class ReportChapter:
    """Un chapitre du canevas, avec ses tableaux dans l'ordre officiel."""

    title: str
    tables: tuple[ReportTable, ...]
    intro: str | None = None


@dataclass
class DeepReport:
    """Le rapport complet, prêt à rendre."""

    academic_year_name: str
    trimester: int
    chapters: list[ReportChapter] = field(default_factory=list)
    conclusion: str = ""

    @property
    def pending_table_numbers(self) -> list[int]:
        """Numéros des tableaux que la plateforme ne sait pas produire."""
        return sorted(
            {table.number for chapter in self.chapters for table in chapter.tables if table.pending}
        )
