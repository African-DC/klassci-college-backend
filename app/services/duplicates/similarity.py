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
from typing import Protocol

# Ce que pèse chaque champ. Le nom et le prénom portent l'essentiel parce
# qu'ils sont toujours saisis ; la date de naissance départage les homonymes,
# qui sont nombreux ici — un « KOUASSI Aya » par classe n'a rien d'exceptionnel.
#
# Le LIEU de naissance a été retiré. À Bouaké il est le même pour presque tout
# l'effectif : lui laisser un poids fabriquait du signal à partir d'un champ
# sans pouvoir discriminant, et pouvait à lui seul faire basculer un couple
# au-dessus du seuil.
POIDS = {"last_name": 0.40, "first_name": 0.35, "birth_date": 0.25}

# En dessous, deux fiches ne se ressemblent pas assez pour qu'on dérange
# quelqu'un ; au-dessus du seuil haut, on considère que c'est la même personne.
SEUIL_SIGNALEMENT = 0.72
SEUIL_QUASI_CERTAIN = 0.90


def normaliser(valeur: str | None) -> str:
    """Réduit un nom à ce qui compte pour le comparer.

    « KOUAMÉ », « kouame » et « Kouamé  » désignent la même personne. Les
    accents sont retirés parce qu'ils sont saisis de façon irrégulière au
    copier-coller, et les traits d'union parce que « MARIE-LINE » et
    « MARIE LINE » s'écrivent au hasard du clavier.
    """
    if not valeur:
        return ""
    sans_accent = "".join(
        c for c in unicodedata.normalize("NFD", valeur) if unicodedata.category(c) != "Mn"
    )
    lettres = [c if c.isalnum() else " " for c in sans_accent.lower()]
    return " ".join("".join(lettres).split())


def compact(valeur: str | None) -> str:
    """La forme comparable d'un nom, sans espaces ni ponctuation.

    « N'DRI », « NDRI » et « n dri » doivent se trouver. La préfiltre SQL
    utilise le même compactage, sinon un nom saisi sans apostrophe ne
    ramènerait jamais la fiche qui en a une.
    """
    return normaliser(valeur).replace(" ", "")


class Identite(Protocol):
    last_name: str | None
    first_name: str | None
    birth_date: date | None


@dataclass(frozen=True)
class StudentIdentity:
    """Les quatre champs qui identifient un élève quand le matricule manque."""

    last_name: str | None
    first_name: str | None
    birth_date: date | None = None


def _bigrammes(texte: str) -> set[str]:
    colle = texte.replace(" ", "")
    return {colle[i : i + 2] for i in range(len(colle) - 1)}


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

    Sauf un cas fréquent au copier-coller : le jour et le mois intervertis,
    quand la famille dicte « 04/05 » et que la saisie hésite entre les deux
    ordres.
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
    #: Les champs que la SAISIE portait, comparables ou non. C'est sur eux que
    #: se decide le declenchement : une fiche stockee incomplete doit remonter
    #: avec une confiance reduite, pas etre condamnee au silence.
    champs_saisis: tuple[str, ...]
    champs_manquants: tuple[str, ...]

    @property
    def saisie_suffisante(self) -> bool:
        """Le nom, plus au moins un second element d'identite."""
        saisis = set(self.champs_saisis)
        return "last_name" in saisis and bool(saisis & {"first_name", "birth_date"})

    @property
    def quasi_certain(self) -> bool:
        return self.score >= SEUIL_QUASI_CERTAIN

    @property
    def a_signaler(self) -> bool:
        return self.saisie_suffisante and self.score >= SEUIL_SIGNALEMENT

    @property
    def juge_sur_peu(self) -> bool:
        """Vrai quand la naissance manque des deux côtés.

        Seule la date departage vraiment : a Bouake, le lieu de naissance
        est le meme pour presque tout le monde. Le compter comme un etat civil
        corrobore gonflait le score ET faisait taire cet avertissement, ce qui
        est le pire des deux mondes.

        C'est exactement le cas des fiches reprises d'un ancien systeme, et
        l'ecran doit le dire au lieu d'afficher un pourcentage qui inspire une
        confiance qu'il ne merite pas.
        """
        return bool(self.champs_manquants)


def comparer(saisie: Identite, existante: Identite) -> Ressemblance:
    """Compare la fiche saisie a une fiche existante.

    Les deux arguments ne sont PAS interchangeables : `champs_saisis`, et donc
    le declenchement, se lisent sur la premiere. Les poids sont renormalises
    sur les seuls champs comparables, pour que deux fiches sans etat civil se
    jugent sur nom et prenom a parts egales plutot que de plafonner par le seul
    fait qu'il manque des donnees.
    """
    details: dict[str, float] = {}
    manquants: list[str] = []

    for champ in ("last_name", "first_name"):
        r = ressemblance_texte(getattr(saisie, champ), getattr(existante, champ))
        if r is None:
            manquants.append(champ)
        else:
            details[champ] = r

    r_date = ressemblance_date(saisie.birth_date, existante.birth_date)
    if r_date is None:
        manquants.append("birth_date")
    else:
        details["birth_date"] = r_date

    total_poids = sum(POIDS[c] for c in details)
    score = sum(details[c] * POIDS[c] for c in details) / total_poids if total_poids else 0.0

    # Ce que la SAISIE portait, sans `getattr` : le protocole declare ces
    # attributs, les lire directement laisse le verificateur de types faire son
    # travail.
    valeurs_saisies = {
        "last_name": saisie.last_name,
        "first_name": saisie.first_name,
        "birth_date": saisie.birth_date,
    }
    saisis = tuple(champ for champ, valeur in valeurs_saisies.items() if valeur)
    return Ressemblance(
        score=round(score, 4),
        champs_compares=tuple(details),
        champs_saisis=saisis,
        champs_manquants=tuple(manquants),
    )
