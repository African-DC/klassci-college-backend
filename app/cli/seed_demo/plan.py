"""Le plan de l'établissement : structure, programme et grille tarifaire.

Pur : que des constantes et des fonctions sans I/O. C'est le document qu'on
relit quand on se demande « d'où sort ce chiffre » pendant la démonstration, et
c'est le seul fichier à modifier pour changer la taille de l'école.

L'établissement modélisé est un collège-lycée privé ivoirien : sept niveaux de
la 6e à la Terminale, les séries A et C en seconde, A, C et D au second cycle,
et le nombre de divisions qu'un effectif réel justifie.
"""

from __future__ import annotations

import hashlib
import unicodedata
from decimal import Decimal

#: Nom canonique de chaque niveau, son rang, et les graphies déjà rencontrées
#: dans les bases existantes. Les alias servent à **retrouver** un niveau saisi
#: autrement (« Terminal », « Seconde », « première ») plutôt qu'à en créer un
#: second sous un nom voisin.
LEVELS: tuple[tuple[str, int, tuple[str, ...]], ...] = (
    ("6ème", 1, ("6eme", "6e", "sixieme")),
    ("5ème", 2, ("5eme", "5e", "cinquieme")),
    ("4ème", 3, ("4eme", "4e", "quatrieme")),
    ("3ème", 4, ("3eme", "3e", "troisieme")),
    ("2nde", 5, ("2nde", "2de", "seconde")),
    ("1ère", 6, ("1ere", "1re", "premiere")),
    ("Terminale", 7, ("terminale", "terminal", "tle", "tl", "term")),
)

#: Séries par niveau de lycée. En Côte d'Ivoire la série D n'ouvre qu'en
#: première : une seconde se fait en A (littéraire) ou en C (scientifique).
SERIES: dict[str, tuple[str, ...]] = {
    "2nde": ("A", "C"),
    "1ère": ("A", "C", "D"),
    "Terminale": ("A", "C", "D"),
}

#: Divisions par niveau de collège. C'est là que les familles inscrivent en
#: masse, donc là que l'école dédouble ; au lycée, la série tient lieu de
#: division.
DIVISIONS: dict[str, tuple[str, ...]] = {
    "6ème": ("A", "B", "C"),
    "5ème": ("A", "B", "C"),
    "4ème": ("A", "B"),
    "3ème": ("A", "B"),
}

#: Effectif visé par classe, dans la fourchette réelle d'un privé ivoirien.
CLASS_SIZE_MIN = 35
CLASS_SIZE_MAX = 48


def normalize(value: str) -> str:
    """Réduit un libellé à ses lettres et chiffres, sans accents ni casse.

    C'est la clé de rapprochement de tout le semis : « 1ere C », « 1ère C » et
    « 1re C » désignent la même classe, et en créer trois ferait trois listes
    d'appel là où l'école n'en tient qu'une.
    """
    decomposed = unicodedata.normalize("NFKD", value)
    ascii_only = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return "".join(ch for ch in ascii_only if ch.isalnum()).lower()


def level_aliases(canonical: str) -> set[str]:
    """Toutes les graphies sous lesquelles ce niveau peut déjà exister."""
    for name, _order, aliases in LEVELS:
        if name == canonical:
            return {normalize(name), *(normalize(alias) for alias in aliases)}
    return {normalize(canonical)}


def series_token(name: str) -> str:
    """La lettre d'une série, quelle que soit la façon dont elle est écrite.

    « serie A », « Série A » et « A » désignent la même série ; sans ce
    rabotage, le semis en ouvrirait une seconde à côté de celle qui existe.
    """
    reduced = normalize(name)
    for prefix in ("serie", "series"):
        if reduced.startswith(prefix):
            reduced = reduced[len(prefix) :]
    return reduced.upper()


def division_token(class_name: str) -> str:
    """La division d'un nom de classe : sa dernière composante, en majuscules.

    Sert à reconnaître « Tle A » comme la Terminale A déjà ouverte, sans quoi le
    semis en créerait une seconde sous son nom canonique.
    """
    parts = class_name.replace("-", " ").split()
    return parts[-1].upper() if parts else ""


def class_plan() -> list[tuple[str, str | None, str]]:
    """Les classes à ouvrir : (niveau, série, division).

    Une classe de collège n'a pas de série ; au lycée, la série **est** la
    division : on n'ouvre pas de « Terminale D 2 » tant qu'une seule suffit.
    """
    plan: list[tuple[str, str | None, str]] = []
    for level, _order, _aliases in LEVELS:
        if level in SERIES:
            plan.extend((level, serie, serie) for serie in SERIES[level])
        else:
            plan.extend((level, None, division) for division in DIVISIONS[level])
    return plan


def class_size(level: str, serie: str | None, division: str) -> int:
    """L'effectif visé d'une division, dérivé de son seul nom.

    Dérivé du nom, et non tiré au fil de l'exécution : la capacité de la classe
    est posée par l'étape référentiel et les élèves sont inscrits par l'étape
    familles. Deux tirages successifs dans le même flux donneraient deux
    nombres différents, et la classe se déclarerait pleine au trente-sixième
    élève. Un condensé du nom donne la même valeur aux deux endroits, et la
    même à chaque relance.
    """
    key = f"{level}/{serie or ''}/{division}".encode()
    spread = CLASS_SIZE_MAX - CLASS_SIZE_MIN + 1
    return CLASS_SIZE_MIN + hashlib.sha256(key).digest()[0] % spread


#: Places laissées libres au-dessus de l'effectif visé. Une classe remplie au
#: dernier siège refuserait la première inscription de l'année suivante.
CLASS_HEADROOM = 5


def class_display_name(level: str, division: str) -> str:
    """Le nom affiché sur la porte de la salle."""
    return f"{level} {division}"


# ---------------------------------------------------------------------------
# Programme et coefficients
# ---------------------------------------------------------------------------

_COLLEGE_BASE: tuple[tuple[str, int, int], ...] = (
    ("Français", 4, 5),
    ("Mathématiques", 4, 5),
    ("Anglais", 2, 3),
    ("Histoire-Géographie", 2, 3),
    ("Sciences de la Vie et de la Terre", 2, 2),
    ("Éducation Physique et Sportive", 1, 2),
)
_PHYSIQUE = ("Physique-Chimie", 2, 3)
_ESPAGNOL = ("Espagnol", 2, 3)
_ALLEMAND = ("Allemand", 2, 3)

#: Matière → (coefficient, heures hebdomadaires). Les coefficients suivent le
#: programme ivoirien : français et mathématiques dominent au collège, la série
#: redistribue les poids au lycée, et la philosophie n'ouvre qu'en Terminale.
CURRICULUM: dict[str, tuple[tuple[str, int, int], ...]] = {
    # Collège : la physique-chimie et la seconde langue ouvrent en 4e.
    "6ème": _COLLEGE_BASE,
    "5ème": _COLLEGE_BASE,
    "4ème": (*_COLLEGE_BASE, _PHYSIQUE, _ESPAGNOL),
    "3ème": (*_COLLEGE_BASE, _PHYSIQUE, _ESPAGNOL),
    # Lycée : la série redistribue les coefficients.
    "2nde/A": (
        ("Français", 4, 5),
        ("Anglais", 3, 4),
        _ESPAGNOL,
        ("Histoire-Géographie", 3, 4),
        ("Mathématiques", 2, 3),
        ("Sciences de la Vie et de la Terre", 2, 2),
        ("Physique-Chimie", 2, 2),
        ("Éducation Physique et Sportive", 1, 2),
    ),
    "2nde/C": (
        ("Mathématiques", 4, 6),
        ("Physique-Chimie", 4, 5),
        ("Sciences de la Vie et de la Terre", 2, 3),
        ("Français", 3, 4),
        ("Anglais", 2, 3),
        ("Histoire-Géographie", 2, 2),
        ("Éducation Physique et Sportive", 1, 2),
    ),
    "1ère/A": (
        ("Français", 5, 6),
        ("Anglais", 3, 4),
        _ALLEMAND,
        ("Histoire-Géographie", 3, 4),
        ("Mathématiques", 2, 3),
        ("Sciences de la Vie et de la Terre", 2, 2),
        ("Éducation Physique et Sportive", 1, 2),
    ),
    "1ère/C": (
        ("Mathématiques", 5, 7),
        ("Physique-Chimie", 4, 5),
        ("Sciences de la Vie et de la Terre", 2, 3),
        ("Français", 3, 4),
        ("Anglais", 2, 3),
        ("Histoire-Géographie", 2, 2),
        ("Éducation Physique et Sportive", 1, 2),
    ),
    "1ère/D": (
        ("Mathématiques", 4, 5),
        ("Physique-Chimie", 4, 5),
        ("Sciences de la Vie et de la Terre", 4, 5),
        ("Français", 3, 4),
        ("Anglais", 2, 3),
        ("Histoire-Géographie", 2, 2),
        ("Éducation Physique et Sportive", 1, 2),
    ),
    "Terminale/A": (
        ("Philosophie", 5, 6),
        ("Français", 4, 5),
        ("Anglais", 3, 4),
        _ALLEMAND,
        ("Histoire-Géographie", 3, 4),
        ("Mathématiques", 2, 3),
        ("Éducation Physique et Sportive", 1, 2),
    ),
    "Terminale/C": (
        ("Mathématiques", 5, 7),
        ("Physique-Chimie", 5, 6),
        ("Sciences de la Vie et de la Terre", 2, 3),
        ("Philosophie", 2, 3),
        ("Français", 2, 3),
        ("Anglais", 2, 3),
        ("Histoire-Géographie", 2, 2),
        ("Éducation Physique et Sportive", 1, 2),
    ),
    "Terminale/D": (
        ("Sciences de la Vie et de la Terre", 5, 6),
        ("Mathématiques", 4, 5),
        ("Physique-Chimie", 4, 5),
        ("Philosophie", 2, 3),
        ("Français", 2, 3),
        ("Anglais", 2, 3),
        ("Histoire-Géographie", 2, 2),
        ("Éducation Physique et Sportive", 1, 2),
    ),
}


def curriculum_for(level: str, serie: str | None) -> tuple[tuple[str, int, int], ...]:
    """Le programme d'une classe : par série au lycée, par niveau au collège."""
    if serie is not None:
        return CURRICULUM[f"{level}/{serie}"]
    return CURRICULUM[level]


def all_subject_names() -> list[str]:
    """Le catalogue des matières, dans un ordre stable."""
    seen: list[str] = []
    for entries in CURRICULUM.values():
        for name, _coefficient, _hours in entries:
            if name not in seen:
                seen.append(name)
    return seen


# ---------------------------------------------------------------------------
# Grille tarifaire du collège pilote
# ---------------------------------------------------------------------------

#: Catégories de frais et leur rang d'allocation. Un versement se règle dans
#: cet ordre. L'inscription d'abord, c'est elle qui valide le dossier, puis la
#: scolarité ensuite, puis le reste.
FEE_CATEGORIES: tuple[tuple[str, int, str], ...] = (
    ("Inscription", 10, "Frais d'inscription annuels, dus par toutes les familles"),
    ("Scolarité", 20, "Scolarité annuelle, due par les élèves non affectés par l'État"),
    ("Tenue scolaire", 40, "Tenue réglementaire de l'établissement"),
    ("Cours de soutien", 50, "Renforcement des classes d'examen"),
    ("Droit d'examen", 60, "Frais de présentation au BEPC ou au BAC"),
)

#: La tenue est due partout, au même prix.
UNIFORM_FEE = Decimal("18000")

#: Ce que chaque niveau facture, en francs CFA, hors tenue. Une catégorie
#: absente ne s'applique pas au niveau : la 6e ne paie ni soutien ni droit
#: d'examen. La scolarité n'est due que par les non affectés, un élève affecté
#: par l'État est subventionné.
FEE_GRID: dict[str, dict[str, Decimal]] = {
    "6ème": {"Inscription": Decimal("37000"), "Scolarité": Decimal("70000")},
    "5ème": {"Inscription": Decimal("37000"), "Scolarité": Decimal("70000")},
    "4ème": {"Inscription": Decimal("37000"), "Scolarité": Decimal("90000")},
    "3ème": {
        "Inscription": Decimal("37000"),
        "Scolarité": Decimal("110000"),
        "Cours de soutien": Decimal("18000"),
        "Droit d'examen": Decimal("2000"),
    },
    "2nde": {"Inscription": Decimal("37000"), "Scolarité": Decimal("100000")},
    "1ère": {"Inscription": Decimal("37000"), "Scolarité": Decimal("100000")},
    "Terminale": {
        "Inscription": Decimal("37000"),
        "Scolarité": Decimal("120000"),
        "Cours de soutien": Decimal("18000"),
        "Droit d'examen": Decimal("5000"),
    },
}

#: Catégories réservées aux élèves non affectés par l'État.
NON_AFFECTED_ONLY: frozenset[str] = frozenset({"Scolarité"})


def fees_for_level(level: str) -> dict[str, Decimal]:
    """La grille d'un niveau, tenue comprise."""
    return {**FEE_GRID[level], "Tenue scolaire": UNIFORM_FEE}


def total_due(level: str, *, subsidised: bool) -> Decimal:
    """Ce qu'une famille de ce niveau doit sur l'année.

    Un élève affecté ne doit pas la scolarité : c'est l'État qui la prend en
    charge. C'est la seule différence entre les deux tarifs, et elle est
    considérable : 70 000 F sur une 6e, 120 000 sur une Terminale.
    """
    grid = fees_for_level(level)
    return sum(
        (amount for name, amount in grid.items() if not (subsidised and name in NON_AFFECTED_ONLY)),
        Decimal("0"),
    )


#: Grille de tranches de l'établissement, telle que la brochure l'annonce :
#: l'inscription en francs, le reste en pourcentages du solde. `(nom, rang,
#: est_ferme, valeur, mois, jour)`, l'année est celle de l'année scolaire.
INSTALLMENT_GRID: tuple[tuple[str, int, bool, Decimal, int, int], ...] = (
    ("Inscription", 1, True, Decimal("37000"), 9, 15),
    ("Fin novembre", 2, False, Decimal("35"), 11, 30),
    ("Fin janvier", 3, False, Decimal("35"), 1, 31),
    ("Fin mars", 4, False, Decimal("30"), 3, 31),
)
