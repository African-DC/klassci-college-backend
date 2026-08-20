"""Seuils, cycles et agrégats du rapport DEEP — fonctions pures, testées.

Ce sont les chiffres que l'inspection relit ligne à ligne. Une inégalité
stricte posée à l'envers ne se voit pas à l'œil nu et fausse tout un
récapitulatif, d'où l'isolement de ces règles dans un module sans accès
base de données.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from decimal import Decimal

from app.services.deep_report._types import MISSING

# Seuils du canevas. « Moy ≥ 10 », « 08.50 ≤ Moy < 10.00 », « Moy < 08.50 » :
# les bornes appartiennent à la tranche du dessus, exactement comme sur le
# document officiel.
PASS_THRESHOLD = Decimal("10")
BORDERLINE_THRESHOLD = Decimal("8.5")


class GradeBand(str, enum.Enum):
    """Tranche de moyenne au sens du canevas DEEP."""

    PASS = "pass"  # Moy >= 10.00
    BORDERLINE = "borderline"  # 08.50 <= Moy < 10.00
    FAIL = "fail"  # Moy < 08.50


def band_of(average: Decimal | None) -> GradeBand | None:
    """Tranche d'une moyenne trimestrielle. `None` si l'élève n'est pas classé."""
    if average is None:
        return None
    if average >= PASS_THRESHOLD:
        return GradeBand.PASS
    if average >= BORDERLINE_THRESHOLD:
        return GradeBand.BORDERLINE
    return GradeBand.FAIL


class Cycle(enum.IntEnum):
    """Les deux cycles du secondaire général ivoirien."""

    FIRST = 1  # 6ème à 3ème
    SECOND = 2  # Seconde à Terminale


_SECOND_CYCLE_MARKERS = (
    "terminale",
    "tle",
    "tl",
    "seconde",
    "2nde",
    "2de",
    "premiere",
    "1ere",
    "1re",
)
_FIRST_CYCLE_MARKERS = ("6", "5", "4", "3")


def _normalise(label: str) -> str:
    """Minuscule sans accents ni ponctuation, pour comparer des noms de niveau."""
    lowered = label.strip().lower()
    for accented, plain in (("é", "e"), ("è", "e"), ("ê", "e"), ("à", "a"), ("î", "i")):
        lowered = lowered.replace(accented, plain)
    return "".join(char for char in lowered if char.isalnum())


def cycle_of_level(level_name: str, level_order: int) -> Cycle:
    """Cycle d'un niveau, déduit de son nom puis, à défaut, de son rang.

    Le nom prime : une école peut numéroter ses niveaux comme elle veut, mais
    « Terminale » reste le second cycle. Le rang ne sert que de filet quand le
    nom n'évoque rien de connu — les quatre premiers niveaux formant le
    premier cycle dans le cursus ivoirien.
    """
    normalised = _normalise(level_name)
    for marker in _SECOND_CYCLE_MARKERS:
        if normalised.startswith(marker):
            return Cycle.SECOND
    for marker in _FIRST_CYCLE_MARKERS:
        if normalised.startswith(marker):
            return Cycle.FIRST
    return Cycle.FIRST if level_order <= 4 else Cycle.SECOND


@dataclass(frozen=True)
class SexCount:
    """Un décompte ventilé filles / garçons.

    `unknown` isole les élèves dont le sexe n'est pas renseigné : les compter
    d'office dans l'une des deux colonnes fausserait la ventilation, et les
    oublier du total ferait mentir l'effectif.
    """

    girls: int = 0
    boys: int = 0
    unknown: int = 0

    @property
    def total(self) -> int:
        return self.girls + self.boys + self.unknown

    def __add__(self, other: SexCount) -> SexCount:
        return SexCount(
            girls=self.girls + other.girls,
            boys=self.boys + other.boys,
            unknown=self.unknown + other.unknown,
        )

    def plus(self, *, girl: bool | None) -> SexCount:
        """Incrémente la bonne colonne. `girl=None` → sexe non renseigné."""
        if girl is None:
            return SexCount(self.girls, self.boys, self.unknown + 1)
        if girl:
            return SexCount(self.girls + 1, self.boys, self.unknown)
        return SexCount(self.girls, self.boys + 1, self.unknown)


@dataclass(frozen=True)
class BandTally:
    """Récapitulatif d'un groupe (une classe, un niveau, l'établissement).

    `real` = effectif inscrit. `ranked` = élèves effectivement classés, c'est
    à dire porteurs d'une moyenne trimestrielle. Les pourcentages du canevas
    se calculent sur les classés : un élève sans bulletin n'a pas échoué, il
    n'a pas été évalué.
    """

    real: SexCount = SexCount()
    ranked: SexCount = SexCount()
    passed: SexCount = SexCount()
    borderline: SexCount = SexCount()
    failed: SexCount = SexCount()

    def __add__(self, other: BandTally) -> BandTally:
        return BandTally(
            real=self.real + other.real,
            ranked=self.ranked + other.ranked,
            passed=self.passed + other.passed,
            borderline=self.borderline + other.borderline,
            failed=self.failed + other.failed,
        )

    def with_student(self, *, girl: bool | None, average: Decimal | None) -> BandTally:
        """Ajoute un élève au récapitulatif."""
        band = band_of(average)
        if band is None:
            return BandTally(
                real=self.real.plus(girl=girl),
                ranked=self.ranked,
                passed=self.passed,
                borderline=self.borderline,
                failed=self.failed,
            )
        return BandTally(
            real=self.real.plus(girl=girl),
            ranked=self.ranked.plus(girl=girl),
            passed=self.passed.plus(girl=girl) if band is GradeBand.PASS else self.passed,
            borderline=(
                self.borderline.plus(girl=girl) if band is GradeBand.BORDERLINE else self.borderline
            ),
            failed=self.failed.plus(girl=girl) if band is GradeBand.FAIL else self.failed,
        )


def sum_tallies(tallies: list[BandTally]) -> BandTally:
    """Somme d'une liste de récapitulatifs — total d'un niveau, d'un cycle."""
    result = BandTally()
    for tally in tallies:
        result = result + tally
    return result


def percentage(part: int, whole: int) -> str:
    """Pourcentage formaté à la française, ou « — » si le dénominateur est nul.

    Renvoyer « 0,0 % » sur un effectif classé nul reviendrait à affirmer un
    taux d'échec de zéro alors qu'aucun élève n'a été évalué.
    """
    if whole <= 0:
        return MISSING
    return f"{(part / whole) * 100:.1f}".replace(".", ",") + " %"


def format_average(average: Decimal | None) -> str:
    """Moyenne sur 20, virgule française. « — » si l'élève n'est pas classé."""
    if average is None:
        return MISSING
    return f"{average:.2f}".replace(".", ",")
