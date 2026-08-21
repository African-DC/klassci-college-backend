"""Répertoire onomastique ivoirien : patronymes, prénoms, communes, téléphones.

Pur : aucune I/O, aucune session. Ce module ne fait que proposer des noms
plausibles à partir d'un tirage reproductible, ce qui le rend testable seul.

Le mélange voulu est celui d'une cour de récréation d'Abidjan ou de Bouaké :
des jours de naissance akan (Kouassi, Adjoua), des prénoms musulmans du nord
(Aminata, Souleymane) et des prénoms français hérités de l'école coloniale
(Chantal, Hervé), tous portés par les mêmes patronymes.
"""

from __future__ import annotations

import random
import unicodedata

#: Patronymes. Volontairement larges : akan, malinké, sénoufo, bété, dioula.
LAST_NAMES: tuple[str, ...] = (
    "Kouassi",
    "N'Guessan",
    "Traoré",
    "Koné",
    "Ouattara",
    "Yao",
    "Bamba",
    "Cissé",
    "Diomandé",
    "Gbagbo",
    "Kouamé",
    "Sangaré",
    "Touré",
    "Zadi",
    "Konan",
    "Aka",
    "Assi",
    "Brou",
    "Coulibaly",
    "Diabaté",
    "Doumbia",
    "Fofana",
    "Gnahoré",
    "Kanga",
    "Kouadio",
    "Lorougnon",
    "Méledje",
    "N'Dri",
    "Oulaï",
    "Sanogo",
    "Silué",
    "Tanoh",
    "Tapé",
    "Vanié",
    "Wodié",
    "Yéo",
    "Zoro",
    "Adjoumani",
    "Beugré",
    "Digbeu",
    "Ekra",
    "Guédé",
    "Kacou",
    "Loba",
    "Séry",
    "Zamblé",
    "Attoungbré",
    "Bohoussou",
    "Djédjé",
    "Aboua",
)

#: Prénoms masculins, jour akan, puis nord musulman, puis français.
FIRST_NAMES_M: tuple[str, ...] = (
    "Kouassi",
    "Kouadio",
    "Konan",
    "Kouakou",
    "Yao",
    "Koffi",
    "Kouamé",
    "Aboubacar",
    "Ibrahim",
    "Mamadou",
    "Sékou",
    "Moussa",
    "Adama",
    "Souleymane",
    "Youssouf",
    "Karim",
    "Lassina",
    "Zoumana",
    "Vamara",
    "Jean-Baptiste",
    "Serge",
    "Hervé",
    "Patrick",
    "Emmanuel",
    "Franck",
    "Olivier",
    "Arsène",
    "Cédric",
    "Rodrigue",
    "Wilfried",
    "Yannick",
    "Aristide",
    "Désiré",
    "Fabrice",
    "Isaac",
    "Landry",
    "Marius",
    "Narcisse",
    "Prosper",
    "Romaric",
    "Sylvain",
    "Thierry",
    "Ulrich",
    "Valentin",
)

#: Prénoms féminins, même logique.
FIRST_NAMES_F: tuple[str, ...] = (
    "Adjoua",
    "Amenan",
    "Affoué",
    "Akissi",
    "Ahou",
    "Aya",
    "Amoin",
    "Aminata",
    "Fatoumata",
    "Mariam",
    "Awa",
    "Kadidiatou",
    "Salimata",
    "Djénéba",
    "Rokia",
    "Assétou",
    "Korotoum",
    "Nadège",
    "Chantal",
    "Solange",
    "Bénédicte",
    "Léa",
    "Estelle",
    "Carine",
    "Rachelle",
    "Prisca",
    "Georgette",
    "Antoinette",
    "Célestine",
    "Danielle",
    "Florence",
    "Grâce",
    "Henriette",
    "Irène",
    "Josiane",
    "Laetitia",
    "Micheline",
    "Nathalie",
    "Odette",
    "Pélagie",
    "Sylvie",
    "Thérèse",
    "Viviane",
    "Yolande",
)

#: Communes et villes où habitent les familles de l'école.
COMMUNES: tuple[str, ...] = (
    "Cocody",
    "Yopougon",
    "Abobo",
    "Adjamé",
    "Treichville",
    "Marcory",
    "Koumassi",
    "Port-Bouët",
    "Attécoubé",
    "Bingerville",
    "Songon",
)
CITIES: tuple[str, ...] = ("Abidjan", "Bouaké", "Yamoussoukro", "Daloa", "San-Pédro")

#: Préfixes mobiles réellement en service en Côte d'Ivoire.
_PHONE_PREFIXES: tuple[str, ...] = ("01", "05", "07", "27")

#: Établissements d'origine cités sur les demandes de dossier scolaire.
PREVIOUS_SCHOOLS: tuple[str, ...] = (
    "Collège Moderne de Cocody",
    "Groupe Scolaire Les Hirondelles",
    "Collège Sainte-Marie de Bouaké",
    "Lycée Municipal d'Abobo",
    "Collège Notre-Dame de Yopougon",
    "EPP Angré 7e Tranche",
)


def strip_accents(value: str) -> str:
    """Version sans accents ni apostrophe : pour les adresses e-mail.

    `N'Guessan` doit donner `nguessan`, pas `n'guessan` : une apostrophe dans
    une adresse est acceptée par la norme mais refusée par la moitié des
    formulaires que les familles rencontreront ensuite.
    """
    decomposed = unicodedata.normalize("NFKD", value)
    ascii_only = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return "".join(ch for ch in ascii_only if ch.isalnum()).lower()


def pick_full_name(rng: random.Random, genre: str) -> tuple[str, str]:
    """Un prénom et un patronyme, accordés au sexe demandé."""
    pool = FIRST_NAMES_M if genre == "M" else FIRST_NAMES_F
    return rng.choice(pool), rng.choice(LAST_NAMES)


def phone_number(rng: random.Random) -> str:
    """Un numéro mobile ivoirien à dix chiffres, préfixe opérateur réel."""
    return f"{rng.choice(_PHONE_PREFIXES)}{rng.randint(0, 99_999_999):08d}"


def email_for(first_name: str, last_name: str, discriminator: int, domain: str) -> str:
    """Adresse déterministe : deux fiches homonymes n'entrent jamais en collision.

    Le discriminant est l'identifiant de rang du semis, pas un hasard : relancer
    le script doit reproduire exactement la même adresse, sinon chaque
    exécution créerait un compte de plus pour la même personne.
    """
    return f"{strip_accents(first_name)}.{strip_accents(last_name)}{discriminator}@{domain}"
