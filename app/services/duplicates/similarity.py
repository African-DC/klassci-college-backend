"""Score de ressemblance entre deux fiches d'élève.

Le matricule ne suffit pas. Une famille qui revient après une année d'absence
se présente sans son papier ; le secrétariat recrée une fiche, et l'élève
existe deux fois — avec deux ardoises séparées, dont une que personne ne
réclamera jamais.

Ce module compare ce qui identifie une personne quand le numéro manque : le
nom, le prénom, la date et le lieu de naissance. Il rend un score et, surtout,
**sur combien de champs il a pu juger**. Un score de 100 % obtenu sur le seul
nom de famille n'a pas la valeur d'un score de 100 % obtenu sur quatre champs,
et l'écran doit pouvoir le dire.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import date

# Ce que pèse chaque champ. Le nom et le prénom portent l'essentiel parce
# qu'ils sont toujours saisis ; la naissance départage les homonymes, qui sont
# nombreux ici — un « KOUASSI Aya » par classe n'a rien d'exceptionnel.
POIDS = {"last_name": 0.30, "first_name": 0.30, "birth_date": 0.25, "birth_place": 0.15}

# En dessous, deux fiches ne se ressemblent pas assez pour qu'on dérange
# quelqu'un ; au-dessus du seuil haut, on considère que c'est la même personne.
SEUIL_SIGNALEMENT = 0.72
SEUIL_QUASI_CERTAIN = 0.90


def normaliser(valeur: str | None) -> str:
    """Réduit un nom à ce qui compte pour le comparer.

    « KOUAMÉ », « kouame » et « Kouamé  » désignent la même personne. Les
    accents sont retirés parce qu'ils sont saisis de façon irrégulière au
    guichet, et les traits d'union parce que « MARIE-LINE » et « MARIE LINE »
    s'écrivent au hasard du clavier.
    """
    if not valeur:
        return ""
    sans_accent = "".join(
        c for c in unicodedata.normalize("NFD", valeur) if unicodedata.category(c) != "Mn"
    )
    lettres = [c if c.isalnum() else " " for c in sans_accent.lower()]
    return " ".join("".join(lettres).split())


def _bigrammes(texte: str) -> set[str]:
    compact = texte.replace(" ", "")
    return {compact[i : i + 2] for i in range(len(compact) - 1)}


def ressemblance_texte(a: str | None, b: str | None) -> float | None:
    """Dice sur les bigrammes : 1.0 identique, 0.0 étranger, None si absent.

    Dice tolère l'inversion et la faute de frappe sans rapprocher n'importe
    quoi : « KOUASSI » et « KOUAKOU » partagent un début mais divergent
    ensuite, et le score le reflète.

    `None` quand l'un des deux manque — ce n'est pas zéro. Une fiche sans lieu
    de naissance ne « diffère » pas de celle qui en a un, elle est muette, et
    la moyenne doit l'ignorer plutôt que de la compter comme un désaccord.
    """
    na, nb = normaliser(a), normaliser(b)
    if not na or not nb:
        return None
    if na == nb:
        return 1.0
    ba, bb = _bigrammes(na), _bigrammes(nb)
    if not ba or not bb:
        return 1.0 if na == nb else 0.0
    return 2 * len(ba & bb) / (len(ba) + len(bb))


def ressemblance_date(a: date | None, b: date | None) -> float | None:
    """Une date de naissance est juste ou fausse ; il n'y a pas d'à-peu-près.

    Sauf un cas fréquent au guichet : le jour et le mois intervertis, quand la
    famille dicte « 04/05 » et que la saisie hésite entre les deux ordres.
    """
    if a is None or b is None:
        return None
    if a == b:
        return 1.0
    if a.year == b.year and a.day == b.month and a.month == b.day:
        return 0.85
    return 0.0


@dataclass(frozen=True)
class Ressemblance:
    """Ce que la comparaison a trouvé, et sur quoi elle s'est appuyée."""

    score: float
    champs_compares: tuple[str, ...]
    champs_manquants: tuple[str, ...]
    details: dict[str, float]

    @property
    def quasi_certain(self) -> bool:
        return self.score >= SEUIL_QUASI_CERTAIN

    @property
    def a_signaler(self) -> bool:
        return self.score >= SEUIL_SIGNALEMENT

    @property
    def juge_sur_peu(self) -> bool:
        """Vrai quand la naissance manque des deux côtés.

        Le score ne repose alors que sur le nom et le prénom. C'est
        exactement le cas des fiches reprises d'un ancien système, et l'écran
        doit le dire au lieu d'afficher un pourcentage qui inspire une
        confiance qu'il ne mérite pas.
        """
        return not ({"birth_date", "birth_place"} & set(self.champs_compares))


def comparer(gauche: object, droite: object) -> Ressemblance:
    """Compare deux fiches sur les champs qu'elles ont en commun.

    Les poids sont renormalisés sur les seuls champs comparables : deux fiches
    sans état civil se jugent sur nom et prénom à parts égales, au lieu de
    plafonner à 60 % par le seul fait qu'il manque des données.
    """
    details: dict[str, float] = {}
    manquants: list[str] = []

    for champ in ("last_name", "first_name", "birth_place"):
        r = ressemblance_texte(getattr(gauche, champ, None), getattr(droite, champ, None))
        if r is None:
            manquants.append(champ)
        else:
            details[champ] = r

    r_date = ressemblance_date(
        getattr(gauche, "birth_date", None), getattr(droite, "birth_date", None)
    )
    if r_date is None:
        manquants.append("birth_date")
    else:
        details["birth_date"] = r_date

    total_poids = sum(POIDS[c] for c in details)
    score = sum(details[c] * POIDS[c] for c in details) / total_poids if total_poids else 0.0

    return Ressemblance(
        score=round(score, 4),
        champs_compares=tuple(details),
        champs_manquants=tuple(manquants),
        details=details,
    )
